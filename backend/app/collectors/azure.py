"""Azure collector: Cost Management Query API for spend, Compute + Monitor for VMs and CPU.

Authentication uses azure-identity's DefaultAzureCredential (service principal env vars
AZURE_TENANT_ID / AZURE_CLIENT_ID / AZURE_CLIENT_SECRET, managed identity, or `az login`).
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta, timezone

from .. import pricing
from ..config import Settings
from ..normalize import categorize_service, normalize_environment
from .base import BaseCollector, CostRow, ResourceRow, UtilRow

log = logging.getLogger(__name__)

_CHUNK_DAYS = 7  # keeps each response under the API's 1000-row page limit


def _parse_usage_date(value) -> date:
    s = str(int(value)) if not isinstance(value, str) else value.replace("-", "")[:8]
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def parse_azure_query(columns: list[str], rows: list[list], tag_key: str, account: str = "") -> list[CostRow]:
    """Convert a Cost Management query result (columns + rows) into CostRow objects."""
    idx = {name: i for i, name in enumerate(columns)}
    cost_col = "Cost" if "Cost" in idx else "PreTaxCost"
    out: list[CostRow] = []
    for r in rows:
        service = r[idx["ServiceName"]] or "Unknown"
        tag = r[idx["TagValue"]] if "TagValue" in idx else None
        if "TagKey" in idx and r[idx["TagKey"]] and str(r[idx["TagKey"]]).lower() != tag_key.lower():
            tag = None
        amount = float(r[idx[cost_col]])
        if abs(amount) < 1e-6:
            continue
        out.append(CostRow(
            date=_parse_usage_date(r[idx["UsageDate"]]), provider="azure", service=service,
            resource_type=categorize_service(service), environment=normalize_environment(tag),
            cost=amount, account=account, region="all",
            currency=(r[idx["Currency"]] if "Currency" in idx else "USD") or "USD",
        ))
    return out


class AzureCollector(BaseCollector):
    provider = "azure"
    mode = "live"

    def __init__(self, settings: Settings):
        self.s = settings
        self._cred = None

    @property
    def sub(self) -> str:
        if not self.s.azure_subscription_id:
            raise RuntimeError("AZURE_SUBSCRIPTION_ID is not set")
        return self.s.azure_subscription_id

    def _credential(self):
        if self._cred is None:
            from azure.identity import DefaultAzureCredential

            self._cred = DefaultAzureCredential()
        return self._cred

    # -- connectivity ----------------------------------------------------------
    def check_connection(self) -> tuple[bool, str]:
        try:
            from azure.mgmt.compute import ComputeManagementClient

            client = ComputeManagementClient(self._credential(), self.sub)
            next(iter(client.virtual_machines.list_all()), None)
            return True, f"Authenticated against subscription {self.sub}"
        except Exception as exc:  # noqa: BLE001
            return False, f"{type(exc).__name__}: {exc}"

    # -- costs -----------------------------------------------------------------
    def _query(self, client, start: date, end: date):
        body = {
            "type": "ActualCost",
            "timeframe": "Custom",
            "timePeriod": {"from": f"{start.isoformat()}T00:00:00Z", "to": f"{end.isoformat()}T23:59:59Z"},
            "dataset": {
                "granularity": "Daily",
                "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}},
                "grouping": [
                    {"type": "Dimension", "name": "ServiceName"},
                    {"type": "TagKey", "name": self.s.azure_environment_tag},
                ],
            },
        }
        for attempt in range(4):  # Cost Management throttles aggressively (HTTP 429)
            try:
                return client.query.usage(f"/subscriptions/{self.sub}", body)
            except Exception as exc:  # noqa: BLE001
                if "429" in str(exc) and attempt < 3:
                    time.sleep(2 ** attempt * 5)
                    continue
                raise

    def fetch_costs(self, start: date, end: date) -> list[CostRow]:
        from azure.mgmt.costmanagement import CostManagementClient

        client = CostManagementClient(self._credential())
        rows: list[CostRow] = []
        cursor = start
        while cursor <= end:
            chunk_end = min(cursor + timedelta(days=_CHUNK_DAYS - 1), end)
            result = self._query(client, cursor, chunk_end)
            if getattr(result, "next_link", None):
                log.warning("Azure cost query for %s..%s was paginated; later pages ignored", cursor, chunk_end)
            rows.extend(parse_azure_query([c.name for c in result.columns], result.rows,
                                          self.s.azure_environment_tag, self.sub))
            cursor = chunk_end + timedelta(days=1)
        return rows

    # -- inventory -------------------------------------------------------------
    @staticmethod
    def _rg(resource_id: str) -> str:
        parts = resource_id.split("/")
        return parts[parts.index("resourceGroups") + 1]

    def fetch_resources(self) -> list[ResourceRow]:
        from azure.mgmt.compute import ComputeManagementClient

        compute = ComputeManagementClient(self._credential(), self.sub)
        env_tag = self.s.azure_environment_tag
        out: list[ResourceRow] = []
        for vm in compute.virtual_machines.list_all():
            view = compute.virtual_machines.instance_view(self._rg(vm.id), vm.name)
            power = next((s.code for s in view.statuses if s.code.startswith("PowerState/")), "PowerState/unknown")
            running = power == "PowerState/running"
            size = vm.hardware_profile.vm_size
            recent = self._cpu(vm.id, hours=2) if running else []
            out.append(ResourceRow(
                provider="azure", resource_id=vm.id, name=vm.name, service="Virtual Machines",
                resource_type="compute", size=size,
                environment=normalize_environment((vm.tags or {}).get(env_tag)),
                region=vm.location, state="running" if running else "stopped",
                monthly_cost=(pricing.estimate_monthly("azure", size) or 0.0) if running else 0.0,
                cpu_pct=recent[-1][1] if recent else None,
            ))
        for disk in compute.disks.list():
            if disk.managed_by:  # attached
                continue
            sku = disk.sku.name if disk.sku else "Premium_LRS"
            out.append(ResourceRow(
                provider="azure", resource_id=disk.id, name=disk.name, service="Managed Disks",
                resource_type="storage", size=f"{sku} {disk.disk_size_gb}GB",
                environment=normalize_environment((disk.tags or {}).get(env_tag)),
                region=disk.location, state="unattached",
                monthly_cost=pricing.volume_monthly(disk.disk_size_gb or 0, sku),
            ))
        return out

    # -- utilisation -----------------------------------------------------------
    def _cpu(self, resource_uri: str, hours: int = 0, start: date | None = None, end: date | None = None):
        """Return [(date, avg, max)] from Azure Monitor 'Percentage CPU'."""
        from azure.mgmt.monitor import MonitorManagementClient

        monitor = MonitorManagementClient(self._credential(), self.sub)
        if hours:
            now = datetime.now(timezone.utc)
            span, interval = f"{(now - timedelta(hours=hours)).isoformat()}/{now.isoformat()}", "PT1H"
        else:
            span, interval = f"{start.isoformat()}T00:00:00Z/{(end + timedelta(days=1)).isoformat()}T00:00:00Z", "P1D"
        resp = monitor.metrics.list(resource_uri, timespan=span, interval=interval,
                                    metricnames="Percentage CPU", aggregation="Average,Maximum")
        points = []
        for metric in resp.value:
            for ts in metric.timeseries:
                for d in ts.data:
                    if d.average is not None:
                        points.append((d.time_stamp.date(), round(d.average, 2), round(d.maximum or d.average, 2)))
        return points

    def fetch_utilization(self, start: date, end: date) -> list[UtilRow]:
        rows: list[UtilRow] = []
        for res in self.fetch_resources():
            if res.state != "running" or res.service != "Virtual Machines":
                continue
            for day, avg, mx in self._cpu(res.resource_id, start=start, end=end):
                rows.append(UtilRow(date=day, provider="azure", resource_id=res.resource_id,
                                    cpu_avg=avg, cpu_max=mx))
        return rows
