"""Resource inventory and utilisation views."""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..models import Resource, UtilizationRecord
from .filters import Filters, apply, daterange

SORTS = {
    "monthly_cost": Resource.monthly_cost.desc(),
    "cpu": Resource.cpu_pct.desc(),
    "name": Resource.name.asc(),
}


def _iso(dt):
    return dt.isoformat() + "Z" if dt else None


def list_resources(db: Session, f: Filters, state: str | None = None, search: str | None = None,
                   sort: str = "monthly_cost", limit: int = 500) -> list[dict]:
    stmt = apply(select(Resource), f, Resource, dates=False)
    if state:
        stmt = stmt.where(Resource.state == state)
    if search:
        stmt = stmt.where(func.lower(Resource.name).contains(search.lower()))
    stmt = stmt.order_by(SORTS.get(sort, SORTS["monthly_cost"]), Resource.name).limit(limit)
    return [{
        "provider": r.provider, "resource_id": r.resource_id, "name": r.name, "service": r.service,
        "resource_type": r.resource_type, "size": r.size, "environment": r.environment,
        "region": r.region, "state": r.state, "monthly_cost": round(r.monthly_cost, 2),
        "cpu_pct": r.cpu_pct, "mem_pct": r.mem_pct, "last_seen": _iso(r.last_seen),
    } for r in db.scalars(stmt)]


def utilization_summary(db: Session, f: Filters, settings: Settings | None = None) -> dict:
    s = settings or get_settings()
    rows = list(db.scalars(apply(select(Resource), f, Resource, dates=False)))
    running = [r for r in rows if r.state == "running" and r.cpu_pct is not None]
    cpus = [r.cpu_pct for r in running]
    return {
        "resource_count": len(rows),
        "running": sum(1 for r in rows if r.state == "running"),
        "unattached": sum(1 for r in rows if r.state == "unattached"),
        "stopped": sum(1 for r in rows if r.state == "stopped"),
        "avg_cpu_pct": round(sum(cpus) / len(cpus), 1) if cpus else None,
        "over_utilized": sum(1 for c in cpus if c > s.overused_cpu_threshold),
        "under_utilized": sum(1 for c in cpus if c < s.underused_cpu_threshold),
        "tracked_monthly_cost": round(sum(r.monthly_cost for r in rows), 2),
        "by_provider": [
            {"provider": p, "count": n, "monthly_cost": round(float(c or 0), 2)}
            for p, n, c in db.execute(apply(
                select(Resource.provider, func.count(), func.sum(Resource.monthly_cost)), f, Resource,
                dates=False).group_by(Resource.provider).order_by(Resource.provider))
        ],
    }


def utilization_timeseries(db: Session, f: Filters, group_by: str = "provider") -> dict:
    """Average daily CPU across resources, pivoted for charting."""
    assert f.start and f.end
    col = {"provider": UtilizationRecord.provider, "environment": UtilizationRecord.environment,
           "resource_type": UtilizationRecord.resource_type}[group_by]
    stmt = apply(select(UtilizationRecord.date, col, func.avg(UtilizationRecord.cpu_avg),
                        func.max(UtilizationRecord.cpu_max)), f, UtilizationRecord)
    by_day: dict = defaultdict(dict)
    series: set[str] = set()
    for d, k, avg, mx in db.execute(stmt.group_by(UtilizationRecord.date, col)):
        by_day[d][k] = round(float(avg), 1)
        series.add(k)
    keys = sorted(series)
    data = [{"date": d.isoformat(), **{k: by_day[d].get(k) for k in keys}}
            for d in daterange(f.start, f.end)]
    return {"group_by": group_by, "series": keys, "data": data}
