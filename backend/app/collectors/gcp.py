"""GCP collector.

Important: the Cloud Billing API (billing_v1) exposes billing *accounts* and the SKU
*catalogue*, not the money you spent. Actual cost data is delivered through the Cloud
Billing **BigQuery export**, so spend is read from that table, while the Cloud Billing API
is used to verify access to the billing account. See docs/CLOUD_SETUP.md.

Authentication uses Application Default Credentials (GOOGLE_APPLICATION_CREDENTIALS).
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone

from .. import pricing
from ..config import Settings
from ..normalize import categorize_service, normalize_environment
from .base import BaseCollector, CostRow, ResourceRow, UtilRow

log = logging.getLogger(__name__)

_TABLE_RE = re.compile(r"^[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+$")


def parse_bq_rows(rows: list[dict], account: str = "") -> list[CostRow]:
    """Convert BigQuery billing-export result rows into CostRow objects."""
    out: list[CostRow] = []
    for r in rows:
        amount = float(r["net_cost"] or 0)
        if abs(amount) < 1e-6:
            continue
        usage_date = r["usage_date"]
        if isinstance(usage_date, str):
            usage_date = date.fromisoformat(usage_date)
        out.append(CostRow(
            date=usage_date, provider="gcp", service=r["service"],
            resource_type=categorize_service(r["service"]),
            environment=normalize_environment(r.get("env")), cost=amount,
            account=r.get("project") or account, region=r.get("region") or "global",
            currency=r.get("currency") or "USD",
        ))
    return out


class GcpCollector(BaseCollector):
    provider = "gcp"
    mode = "live"

    def __init__(self, settings: Settings):
        self.s = settings

    # -- connectivity ----------------------------------------------------------
    def check_connection(self) -> tuple[bool, str]:
        try:
            if self.s.gcp_billing_account_id:
                from google.cloud import billing_v1

                acct = billing_v1.CloudBillingClient().get_billing_account(
                    name=f"billingAccounts/{self.s.gcp_billing_account_id}")
                return True, f"Billing account {acct.display_name!r} reachable (open={acct.open_})"
            from google.cloud import bigquery

            bigquery.Client(project=self.s.gcp_project_id or None).query("SELECT 1").result()
            return True, "BigQuery reachable (set GCP_BILLING_ACCOUNT_ID to also verify the billing account)"
        except Exception as exc:  # noqa: BLE001
            return False, f"{type(exc).__name__}: {exc}"

    # -- costs (BigQuery billing export) --------------------------------------
    def fetch_costs(self, start: date, end: date) -> list[CostRow]:
        from google.cloud import bigquery

        table = self.s.gcp_billing_export_table
        if not _TABLE_RE.match(table):
            raise RuntimeError("GCP_BILLING_EXPORT_TABLE must look like project.dataset.table")
        sql = f"""
            SELECT DATE(usage_start_time) AS usage_date,
                   service.description AS service,
                   project.id AS project,
                   IFNULL(location.region, IFNULL(location.location, 'global')) AS region,
                   currency,
                   (SELECT value FROM UNNEST(labels) WHERE key = @label_key LIMIT 1) AS env,
                   SUM(cost) + SUM(IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0)) AS net_cost
            FROM `{table}`
            WHERE DATE(usage_start_time) BETWEEN @start AND @end
            GROUP BY usage_date, service, project, region, currency, env
        """
        job = bigquery.Client(project=self.s.gcp_project_id or None).query(
            sql,
            job_config=bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("label_key", "STRING", self.s.gcp_environment_label),
                bigquery.ScalarQueryParameter("start", "DATE", start),
                bigquery.ScalarQueryParameter("end", "DATE", end),
            ]),
        )
        return parse_bq_rows([dict(r.items()) for r in job.result()], self.s.gcp_project_id)

    # -- inventory -------------------------------------------------------------
    @staticmethod
    def _tail(url: str) -> str:
        return url.rsplit("/", 1)[-1] if url else ""

    def fetch_resources(self) -> list[ResourceRow]:
        from google.cloud import compute_v1

        project = self.s.gcp_project_id
        label = self.s.gcp_environment_label
        out: list[ResourceRow] = []
        cpu_now = self._cpu_series(hours=2)
        for _zone, scoped in compute_v1.InstancesClient().aggregated_list(project=project):
            for inst in scoped.instances:
                mtype = self._tail(inst.machine_type)
                running = inst.status == "RUNNING"
                series = cpu_now.get(str(inst.id))
                out.append(ResourceRow(
                    provider="gcp", resource_id=str(inst.id), name=inst.name,
                    service="Compute Engine", resource_type="compute", size=mtype,
                    environment=normalize_environment(dict(inst.labels).get(label)),
                    region=self._tail(inst.zone), state="running" if running else "stopped",
                    monthly_cost=(pricing.estimate_monthly("gcp", mtype) or 0.0) if running else 0.0,
                    cpu_pct=round(series[-1][1], 1) if running and series else None,
                ))
        for _zone, scoped in compute_v1.DisksClient().aggregated_list(project=project):
            for disk in scoped.disks:
                if disk.users:  # attached
                    continue
                dtype = self._tail(disk.type_)
                out.append(ResourceRow(
                    provider="gcp", resource_id=str(disk.id), name=disk.name,
                    service="Persistent Disk", resource_type="storage",
                    size=f"{dtype} {disk.size_gb}GB",
                    environment=normalize_environment(dict(disk.labels).get(label)),
                    region=self._tail(disk.zone), state="unattached",
                    monthly_cost=pricing.volume_monthly(disk.size_gb, dtype),
                ))
        return out

    # -- utilisation (Cloud Monitoring) ---------------------------------------
    def _cpu_series(self, hours: int = 0, start: date | None = None, end: date | None = None,
                    aligner: str = "ALIGN_MEAN") -> dict[str, list[tuple[date, float]]]:
        from google.cloud import monitoring_v3
        from google.protobuf import duration_pb2, timestamp_pb2

        now = datetime.now(timezone.utc)
        if hours:
            t0, t1, period = now - timedelta(hours=hours), now, 3600
        else:
            t0 = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
            t1 = datetime(end.year, end.month, end.day, tzinfo=timezone.utc) + timedelta(days=1)
            period = 86400
        interval = monitoring_v3.TimeInterval(
            start_time=timestamp_pb2.Timestamp(seconds=int(t0.timestamp())),
            end_time=timestamp_pb2.Timestamp(seconds=int(t1.timestamp())))
        agg = monitoring_v3.Aggregation(
            alignment_period=duration_pb2.Duration(seconds=period),
            per_series_aligner=getattr(monitoring_v3.Aggregation.Aligner, aligner))
        result: dict[str, list[tuple[date, float]]] = {}
        for ts in monitoring_v3.MetricServiceClient().list_time_series(request={
            "name": f"projects/{self.s.gcp_project_id}",
            "filter": 'metric.type="compute.googleapis.com/instance/cpu/utilization"',
            "interval": interval, "aggregation": agg,
            "view": monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
        }):
            iid = ts.resource.labels.get("instance_id", "")
            pts = sorted((p.interval.end_time.date(), p.value.double_value * 100) for p in ts.points)
            result[iid] = pts
        return result

    def fetch_utilization(self, start: date, end: date) -> list[UtilRow]:
        avg = self._cpu_series(start=start, end=end, aligner="ALIGN_MEAN")
        mx = self._cpu_series(start=start, end=end, aligner="ALIGN_MAX")
        rows: list[UtilRow] = []
        for iid, pts in avg.items():
            peaks = dict(mx.get(iid, []))
            for day, value in pts:
                rows.append(UtilRow(date=day, provider="gcp", resource_id=iid,
                                    cpu_avg=round(value, 2), cpu_max=round(peaks.get(day, value), 2)))
        return rows
