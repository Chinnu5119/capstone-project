"""AWS collector: Cost Explorer for spend, EC2/RDS/EBS for inventory, CloudWatch for CPU.

Credentials come from the standard boto3 chain (env vars, shared config, instance role).
Required IAM actions are listed in docs/CLOUD_SETUP.md.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from .. import pricing
from ..config import Settings
from ..normalize import categorize_service, normalize_environment, tag_value
from .base import BaseCollector, CostRow, ResourceRow, UtilRow

log = logging.getLogger(__name__)


def parse_ce_results(results_by_time: list[dict], tag_key: str, account: str = "") -> list[CostRow]:
    """Convert Cost Explorer `ResultsByTime` (grouped by SERVICE + TAG) into CostRow objects."""
    rows: list[CostRow] = []
    for period in results_by_time:
        day = date.fromisoformat(period["TimePeriod"]["Start"])
        for group in period.get("Groups", []):
            keys = group["Keys"]
            service = keys[0]
            env = normalize_environment(tag_value(keys[1], tag_key) if len(keys) > 1 else None)
            amount = float(group["Metrics"]["UnblendedCost"]["Amount"])
            if abs(amount) < 1e-6:
                continue
            rows.append(CostRow(
                date=day, provider="aws", service=service,
                resource_type=categorize_service(service), environment=env, cost=amount,
                account=account, region="all",
                currency=group["Metrics"]["UnblendedCost"].get("Unit", "USD"),
            ))
    return rows


def parse_cw_datapoints(resource_id: str, datapoints: list[dict]) -> list[UtilRow]:
    """Convert CloudWatch daily datapoints (Average/Maximum) into UtilRow objects."""
    rows = []
    for p in datapoints:
        ts = p["Timestamp"]
        day = ts.date() if hasattr(ts, "date") else date.fromisoformat(str(ts)[:10])
        rows.append(UtilRow(date=day, provider="aws", resource_id=resource_id,
                            cpu_avg=round(p["Average"], 2), cpu_max=round(p["Maximum"], 2)))
    return rows


def _tags(tag_list: list[dict] | None) -> dict[str, str]:
    return {t["Key"]: t["Value"] for t in (tag_list or [])}


class AwsCollector(BaseCollector):
    provider = "aws"
    mode = "live"

    def __init__(self, settings: Settings):
        self.s = settings
        self.regions = [r.strip() for r in settings.aws_regions.split(",") if r.strip()]
        self._account = ""

    def _client(self, service: str, region: str | None = None):
        import boto3  # lazy: only needed in live mode

        return boto3.client(service, region_name=region or self.regions[0])

    # -- connectivity ----------------------------------------------------------
    def check_connection(self) -> tuple[bool, str]:
        try:
            ident = self._client("sts").get_caller_identity()
            self._account = ident["Account"]
            return True, f"Authenticated as {ident['Arn']}"
        except Exception as exc:  # noqa: BLE001 - surface any SDK error to the UI
            return False, f"{type(exc).__name__}: {exc}"

    def _account_id(self) -> str:
        if not self._account:
            self._account = self._client("sts").get_caller_identity()["Account"]
        return self._account

    # -- costs -----------------------------------------------------------------
    def fetch_costs(self, start: date, end: date) -> list[CostRow]:
        ce = self._client("ce", "us-east-1")  # Cost Explorer is a global endpoint in us-east-1
        params = {
            "TimePeriod": {"Start": start.isoformat(), "End": (end + timedelta(days=1)).isoformat()},
            "Granularity": "DAILY",
            "Metrics": ["UnblendedCost"],
            "GroupBy": [
                {"Type": "DIMENSION", "Key": "SERVICE"},
                {"Type": "TAG", "Key": self.s.aws_environment_tag},
            ],
        }
        results: list[dict] = []
        token = None
        while True:
            resp = ce.get_cost_and_usage(**params, **({"NextPageToken": token} if token else {}))
            results.extend(resp["ResultsByTime"])
            token = resp.get("NextPageToken")
            if not token:
                break
        return parse_ce_results(results, self.s.aws_environment_tag, self._account_id())

    # -- inventory -------------------------------------------------------------
    def fetch_resources(self) -> list[ResourceRow]:
        out: list[ResourceRow] = []
        env_tag = self.s.aws_environment_tag
        for region in self.regions:
            ec2 = self._client("ec2", region)
            cw = self._client("cloudwatch", region)
            for page in ec2.get_paginator("describe_instances").paginate():
                for res in page["Reservations"]:
                    for inst in res["Instances"]:
                        state = inst["State"]["Name"]
                        if state not in ("running", "stopped"):
                            continue
                        tags = _tags(inst.get("Tags"))
                        itype = inst["InstanceType"]
                        monthly = (pricing.estimate_monthly("aws", itype) or 0.0) if state == "running" else 0.0
                        out.append(ResourceRow(
                            provider="aws", resource_id=inst["InstanceId"],
                            name=tags.get("Name", inst["InstanceId"]), service="Amazon EC2",
                            resource_type="compute", size=itype,
                            environment=normalize_environment(tags.get(env_tag)), region=region,
                            state=state, monthly_cost=monthly,
                            cpu_pct=self._current_cpu(cw, "AWS/EC2", "InstanceId", inst["InstanceId"])
                            if state == "running" else None,
                        ))
            for page in ec2.get_paginator("describe_volumes").paginate(
                Filters=[{"Name": "status", "Values": ["available"]}]
            ):
                for vol in page["Volumes"]:
                    tags = _tags(vol.get("Tags"))
                    out.append(ResourceRow(
                        provider="aws", resource_id=vol["VolumeId"],
                        name=tags.get("Name", vol["VolumeId"]), service="Amazon EBS",
                        resource_type="storage", size=f"{vol['VolumeType']} {vol['Size']}GB",
                        environment=normalize_environment(tags.get(env_tag)), region=region,
                        state="unattached",
                        monthly_cost=pricing.volume_monthly(vol["Size"], vol["VolumeType"]),
                    ))
            rds = self._client("rds", region)
            for page in rds.get_paginator("describe_db_instances").paginate():
                for db in page["DBInstances"]:
                    tags = {t["Key"]: t["Value"] for t in db.get("TagList", [])}
                    running = db["DBInstanceStatus"] == "available"
                    monthly = pricing.estimate_monthly("aws", db["DBInstanceClass"]) or 0.0
                    if db.get("MultiAZ"):
                        monthly *= 2
                    out.append(ResourceRow(
                        provider="aws", resource_id=db["DBInstanceIdentifier"],
                        name=db["DBInstanceIdentifier"], service="Amazon RDS",
                        resource_type="database", size=db["DBInstanceClass"],
                        environment=normalize_environment(tags.get(env_tag)), region=region,
                        state="running" if running else "stopped",
                        monthly_cost=round(monthly, 2) if running else 0.0,
                        cpu_pct=self._current_cpu(cw, "AWS/RDS", "DBInstanceIdentifier",
                                                  db["DBInstanceIdentifier"]) if running else None,
                    ))
        return out

    # -- utilisation -----------------------------------------------------------
    @staticmethod
    def _current_cpu(cw, namespace: str, dim: str, value: str) -> float | None:
        now = datetime.now(timezone.utc)
        resp = cw.get_metric_statistics(
            Namespace=namespace, MetricName="CPUUtilization",
            Dimensions=[{"Name": dim, "Value": value}],
            StartTime=now - timedelta(hours=1), EndTime=now, Period=300, Statistics=["Average"],
        )
        pts = sorted(resp.get("Datapoints", []), key=lambda p: p["Timestamp"])
        return round(pts[-1]["Average"], 1) if pts else None

    def fetch_utilization(self, start: date, end: date) -> list[UtilRow]:
        rows: list[UtilRow] = []
        t0 = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
        t1 = datetime(end.year, end.month, end.day, tzinfo=timezone.utc) + timedelta(days=1)
        for res in self.fetch_resources():
            if res.state != "running" or res.resource_type not in ("compute", "database"):
                continue
            namespace, dim = (("AWS/RDS", "DBInstanceIdentifier") if res.service == "Amazon RDS"
                              else ("AWS/EC2", "InstanceId"))
            cw = self._client("cloudwatch", res.region)
            resp = cw.get_metric_statistics(
                Namespace=namespace, MetricName="CPUUtilization",
                Dimensions=[{"Name": dim, "Value": res.resource_id}],
                StartTime=t0, EndTime=t1, Period=86400, Statistics=["Average", "Maximum"],
            )
            rows.extend(parse_cw_datapoints(res.resource_id, resp.get("Datapoints", [])))
        return rows
