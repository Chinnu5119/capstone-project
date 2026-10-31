"""Deterministic mock collector so the whole stack runs without any cloud account.

The data is synthetic but shaped like real cloud billing: weekly seasonality, slow growth,
per-environment splits, a small number of injected cost anomalies, and a mix of busy, idle,
under-used and over-used resources so the alerting and optimisation features have something
realistic to find. Everything is seeded from the (resource, date) so repeated runs are
identical, which is what makes ingestion idempotent.
"""
from __future__ import annotations

import hashlib
import math
import random
from datetime import date, datetime, timedelta, timezone

from .. import pricing
from ..normalize import categorize_service
from .base import BaseCollector, CostRow, ResourceRow, UtilRow

# (service, base daily USD across all environments)
SERVICES: dict[str, list[tuple[str, float]]] = {
    "aws": [("Amazon EC2", 70), ("Amazon RDS", 40), ("Amazon S3", 8), ("AWS Lambda", 4),
            ("Amazon CloudFront", 6), ("AWS Data Transfer", 9), ("Amazon EKS", 25)],
    "azure": [("Virtual Machines", 60), ("Azure SQL Database", 28), ("Storage Accounts", 7),
              ("Azure Kubernetes Service", 22), ("Bandwidth", 6), ("Azure Cosmos DB", 12)],
    "gcp": [("Compute Engine", 55), ("Cloud SQL", 30), ("Cloud Storage", 6), ("BigQuery", 14),
            ("Kubernetes Engine", 20), ("Cloud Networking", 5)],
}
REGIONS = {
    "aws": ["us-east-1", "eu-west-1"],
    "azure": ["eastus", "westeurope"],
    "gcp": ["us-central1", "europe-west1"],
}
ACCOUNTS = {"aws": "123456789012", "azure": "sub-0000-demo", "gcp": "demo-project"}

_ENV_SHARE = {
    "compute": {"production": 0.60, "staging": 0.15, "development": 0.25},
    "database": {"production": 0.65, "staging": 0.15, "development": 0.20},
    "storage": {"production": 0.80, "staging": 0.08, "development": 0.12},
    "network": {"production": 0.85, "staging": 0.05, "development": 0.10},
    "other": {"production": 0.60, "staging": 0.10, "development": 0.30},
}

# (service, kind) -> deterministic anomalies as (days_before_latest, multiplier)
# so the dashboard has real incidents to detect.
_ANOMALIES = {
    ("aws", "Amazon EC2", "production"): [(2, 2.8)],        # runaway autoscaling
    ("gcp", "BigQuery", "production"): [(0, 4.5)],          # expensive unpartitioned query (latest day)
}

# name, service, size, environment, region idx, profile, explicit monthly cost (None => priced)
_INVENTORY = {
    "aws": [
        ("web-prod-1", "Amazon EC2", "m5.xlarge", "production", 0, "busy", None),
        ("web-prod-2", "Amazon EC2", "m5.xlarge", "production", 0, "busy", None),
        ("api-prod-1", "Amazon EC2", "c5.2xlarge", "production", 0, "hot", None),
        ("api-prod-2", "Amazon EC2", "c5.2xlarge", "production", 1, "busy", None),
        ("batch-prod-1", "Amazon EC2", "r5.2xlarge", "production", 1, "underused", None),
        ("web-stg-1", "Amazon EC2", "m5.large", "staging", 0, "normal", None),
        ("dev-build-1", "Amazon EC2", "c5.2xlarge", "development", 0, "idle", None),
        ("dev-sandbox-1", "Amazon EC2", "m5.xlarge", "development", 0, "underused", None),
        ("dev-test-runner", "Amazon EC2", "t3.large", "development", 0, "normal", None),
        ("orders-db-prod", "Amazon RDS", "db.r5.xlarge", "production", 0, "busy", None),
        ("orders-db-stg", "Amazon RDS", "db.m5.large", "staging", 0, "normal", None),
        ("analytics-db-dev", "Amazon RDS", "db.r5.large", "development", 0, "idle", None),
        ("vol-orphan-snapshots", "Amazon EBS", "gp3 500GB", "production", 0, "unattached", 40.0),
        ("vol-dev-scratch", "Amazon EBS", "gp3 1000GB", "development", 0, "unattached", 80.0),
        ("assets-prod-bucket", "Amazon S3", "standard", "production", 0, "none", 120.0),
    ],
    "azure": [
        ("vm-web-prod-1", "Virtual Machines", "Standard_D4s_v5", "production", 0, "busy", None),
        ("vm-web-prod-2", "Virtual Machines", "Standard_D4s_v5", "production", 1, "busy", None),
        ("vm-api-prod-1", "Virtual Machines", "Standard_D8s_v5", "production", 0, "hot", None),
        ("vm-worker-prod", "Virtual Machines", "Standard_E8s_v5", "production", 0, "underused", None),
        ("vm-stg-app", "Virtual Machines", "Standard_D4s_v5", "staging", 0, "normal", None),
        ("vm-dev-jump", "Virtual Machines", "Standard_D2s_v5", "development", 0, "idle", None),
        ("vm-dev-ml", "Virtual Machines", "Standard_E16s_v5", "development", 0, "idle", None),
        ("vm-dev-api", "Virtual Machines", "Standard_D4s_v5", "development", 0, "normal", None),
        ("sql-prod-main", "Azure SQL Database", "GP_Gen5_8", "production", 0, "busy", 920.0),
        ("sql-dev-reporting", "Azure SQL Database", "GP_Gen5_2", "development", 0, "underused", 230.0),
        ("disk-orphan-01", "Managed Disks", "Premium_LRS 256GB", "development", 0, "unattached", 39.4),
        ("stprodassets", "Storage Accounts", "Standard_LRS", "production", 0, "none", 95.0),
    ],
    "gcp": [
        ("gce-web-prod-1", "Compute Engine", "n2-standard-4", "production", 0, "busy", None),
        ("gce-web-prod-2", "Compute Engine", "n2-standard-4", "production", 1, "busy", None),
        ("gce-api-prod", "Compute Engine", "n2-standard-8", "production", 0, "busy", None),
        ("gke-prod-pool-1", "Kubernetes Engine", "n2-standard-4", "production", 0, "hot", None),
        ("gce-stg-1", "Compute Engine", "e2-standard-4", "staging", 0, "normal", None),
        ("gce-dev-1", "Compute Engine", "n2-standard-8", "development", 0, "idle", None),
        ("gce-dev-2", "Compute Engine", "e2-standard-8", "development", 0, "underused", None),
        ("gce-dev-3", "Compute Engine", "e2-standard-4", "development", 0, "normal", None),
        ("cloudsql-prod", "Cloud SQL", "db-n1-standard-8", "production", 0, "busy", 640.0),
        ("cloudsql-dev", "Cloud SQL", "db-n1-standard-2", "development", 0, "underused", 160.0),
        ("pd-orphan-1", "Persistent Disk", "pd-ssd 300GB", "staging", 0, "unattached", 51.0),
        ("gcs-prod-data", "Cloud Storage", "standard", "production", 0, "none", 110.0),
    ],
}

# profile -> (mean cpu %, std dev, typical gap between average and peak)
_PROFILES = {
    "busy": (62.0, 7.0, 20.0),
    "normal": (38.0, 7.0, 25.0),
    "hot": (90.0, 3.0, 8.0),
    "underused": (12.0, 3.5, 18.0),
    "idle": (2.0, 0.8, 6.0),
}


def _rid(provider: str, name: str, service: str) -> str:
    h = hashlib.md5(f"{provider}|{name}".encode()).hexdigest()
    prefix = {"aws": "i", "azure": "vm", "gcp": "inst"}[provider]
    if "RDS" in service or "SQL" in service:
        prefix = "db"
    if "EBS" in service or "Disk" in service:
        prefix = "vol"
    if "S3" in service or "Storage" in service:
        return name
    return f"{prefix}-{h[:12]}"


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _daily_util(name: str, profile: str, d: date) -> tuple[float, float, float]:
    mean, sd, gap = _PROFILES[profile]
    rnd = random.Random(f"util|{name}|{d.isoformat()}")
    weekend = 0.8 if d.weekday() >= 5 and profile in ("busy", "normal") else 1.0
    cpu = _clamp(mean * weekend + rnd.gauss(0, sd), 0.3, 99.0)
    cpu_max = _clamp(cpu + gap * 0.6 + abs(rnd.gauss(0, gap * 0.4)), cpu, 100.0)
    mem = _clamp(cpu * 0.9 + 8 + rnd.gauss(0, 3), 1.0, 98.0)
    return round(cpu, 2), round(cpu_max, 2), round(mem, 2)


class MockCollector(BaseCollector):
    mode = "mock"

    def __init__(self, provider: str, today: date | None = None):
        self.provider = provider
        self._today = today

    @property
    def today(self) -> date:
        return self._today or datetime.now(timezone.utc).date()

    def check_connection(self) -> tuple[bool, str]:
        return True, "Mock provider: synthetic data, no credentials required"

    # -- costs -----------------------------------------------------------------
    def fetch_costs(self, start: date, end: date) -> list[CostRow]:
        latest = self.today - timedelta(days=1)
        end = min(end, latest)
        regions = REGIONS[self.provider]
        rows: list[CostRow] = []
        day = start
        while day <= end:
            age = (latest - day).days
            for service, base in SERVICES[self.provider]:
                rtype = categorize_service(service)
                for env, share in _ENV_SHARE[rtype].items():
                    splits = [(regions[0], 0.7), (regions[1], 0.3)] if env == "production" else [(regions[0], 1.0)]
                    for region, region_share in splits:
                        rnd = random.Random(f"{self.provider}|{service}|{env}|{region}|{day.isoformat()}")
                        growth = 1 + 0.0015 * (day - date(2026, 1, 1)).days / 30
                        weekly = 0.85 if (day.weekday() >= 5 and rtype in ("compute", "other")) else 1.0
                        noise = 1 + rnd.uniform(-0.05, 0.05)
                        cost = base * share * region_share * growth * weekly * noise
                        for days_ago, mult in _ANOMALIES.get((self.provider, service, env), []):
                            if age == days_ago:
                                cost *= mult
                        rows.append(CostRow(
                            date=day, provider=self.provider, service=service, resource_type=rtype,
                            environment=env, cost=round(cost, 4), account=ACCOUNTS[self.provider],
                            region=region,
                        ))
            day += timedelta(days=1)
        return rows

    # -- inventory -------------------------------------------------------------
    def _monthly_cost(self, size: str, explicit: float | None) -> float:
        if explicit is not None:
            return explicit
        return pricing.estimate_monthly(self.provider, size) or 0.0

    def fetch_resources(self) -> list[ResourceRow]:
        now = datetime.now(timezone.utc)
        bucket = int(now.timestamp() // 900)  # 15-minute buckets => values drift live
        out: list[ResourceRow] = []
        for name, service, size, env, region_idx, profile, explicit in _INVENTORY[self.provider]:
            rtype = categorize_service(service)
            state = "unattached" if profile == "unattached" else "running"
            cpu = mem = None
            if profile in _PROFILES:
                mean, sd, _ = _PROFILES[profile]
                phase = random.Random(f"phase|{name}").uniform(0, 6.28)
                wobble = math.sin(bucket / 6.0 + phase) * sd * 1.2
                jitter = random.Random(f"now|{name}|{bucket}").gauss(0, sd * 0.4)
                cpu = round(_clamp(mean + wobble + jitter, 0.3, 99.0), 1)
                mem = round(_clamp(cpu * 0.9 + 8, 1.0, 98.0), 1)
            out.append(ResourceRow(
                provider=self.provider, resource_id=_rid(self.provider, name, service), name=name,
                service=service, resource_type=rtype, size=size, environment=env,
                region=REGIONS[self.provider][region_idx], state=state,
                monthly_cost=self._monthly_cost(size, explicit), cpu_pct=cpu, mem_pct=mem,
            ))
        return out

    # -- utilisation history ---------------------------------------------------
    def fetch_utilization(self, start: date, end: date) -> list[UtilRow]:
        end = min(end, self.today - timedelta(days=1))
        rows: list[UtilRow] = []
        for name, service, _size, _env, _r, profile, _c in _INVENTORY[self.provider]:
            if profile not in _PROFILES:
                continue
            rid = _rid(self.provider, name, service)
            day = start
            while day <= end:
                cpu, cpu_max, mem = _daily_util(name, profile, day)
                rows.append(UtilRow(date=day, provider=self.provider, resource_id=rid,
                                    cpu_avg=cpu, cpu_max=cpu_max, mem_avg=mem))
                day += timedelta(days=1)
        return rows
