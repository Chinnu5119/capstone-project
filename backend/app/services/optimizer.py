"""Cost-optimisation engine: turns utilisation + inventory into ranked, quantified savings.

For each resource exactly one *primary* recommendation is chosen (the one with the largest
saving) so totals never double count. Detection rules:

  unattached  - block volume attached to nothing                 -> delete/snapshot   (100%)
  idle        - running, 14-day avg CPU < 5% and peak < 20%      -> stop/terminate    (100%)
  rightsize   - 14-day avg CPU < 20% and peak < 60%              -> one size down      (~50%)
  schedule    - dev/staging running 24/7                         -> stop off-hours    (~64%)
  commitment  - steady production compute/DB (avg CPU >= 30%)    -> 1-yr commitment   (~30%)
  overused    - 14-day avg CPU > 85%                             -> scale up/out       (risk, no saving)

`commitment` is reported separately from "quick wins" because it needs a purchase decision
and is the least certain estimate. `overused` is a reliability risk, not a saving.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import pricing
from ..config import Settings, get_settings
from ..models import Resource, UtilizationRecord
from .filters import Filters, apply

QUICK_WIN_TYPES = ("unattached", "idle", "rightsize", "schedule")


@dataclass
class UtilStats:
    avg: float | None
    peak: float | None
    days: int


def util_stats(db: Session, f: Filters, window_days: int) -> dict[tuple[str, str], UtilStats]:
    latest = db.scalar(select(func.max(UtilizationRecord.date)))
    if latest is None:
        return {}
    since = latest - timedelta(days=window_days - 1)
    stmt = apply(
        select(UtilizationRecord.provider, UtilizationRecord.resource_id,
               func.avg(UtilizationRecord.cpu_avg), func.max(UtilizationRecord.cpu_max),
               func.count(UtilizationRecord.id)),
        Filters(provider=f.provider, environment=f.environment, resource_type=f.resource_type),
        UtilizationRecord, dates=False).where(UtilizationRecord.date >= since)
    rows = db.execute(stmt.group_by(UtilizationRecord.provider, UtilizationRecord.resource_id))
    return {(p, rid): UtilStats(float(a), float(m), int(n)) for p, rid, a, m, n in rows}


def _rec(res: Resource, kind: str, title: str, action: str, savings: float, confidence: str,
         effort: str, stats: UtilStats | None, detail: str) -> dict:
    return {
        "id": f"{kind}:{res.provider}:{res.resource_id}", "type": kind, "title": title, "action": action,
        "detail": detail, "provider": res.provider, "resource_id": res.resource_id, "name": res.name,
        "service": res.service, "resource_type": res.resource_type, "size": res.size,
        "environment": res.environment, "region": res.region,
        "monthly_cost": round(res.monthly_cost, 2),
        "avg_cpu_pct": round(stats.avg, 1) if stats and stats.avg is not None else None,
        "peak_cpu_pct": round(stats.peak, 1) if stats and stats.peak is not None else None,
        "estimated_monthly_savings": round(savings, 2), "confidence": confidence, "effort": effort,
    }


def recommend_for(res: Resource, stats: UtilStats | None, s: Settings) -> dict | None:
    """The single best recommendation for one resource, or None."""
    cost = res.monthly_cost or 0.0
    nonprod = res.environment in ("development", "staging")
    candidates: list[dict] = []

    if res.state == "unattached":
        return _rec(res, "unattached", "Unattached volume", "Snapshot if needed, then delete the volume",
                    cost, "high", "low", None,
                    f"{res.size} volume is attached to nothing but still billed every month.")
    if res.state != "running" or res.resource_type not in ("compute", "database"):
        return None

    have_util = stats is not None and stats.avg is not None and stats.days >= 3
    if have_util:
        avg, peak = stats.avg, stats.peak or 0.0
        if avg < s.idle_cpu_threshold and peak < 20:
            conf = "high" if nonprod else "medium"
            candidates.append(_rec(
                res, "idle", "Idle resource", "Stop or terminate (snapshot first if state matters)",
                cost, conf, "low", stats,
                f"Average CPU {avg:.1f}% and peak {peak:.1f}% over {stats.days} days."
                + ("" if nonprod else " Production: confirm it is not a warm standby.")))
        elif avg < s.underused_cpu_threshold and peak < 60:
            smaller = pricing.smaller_size(res.provider, res.size)
            if smaller:
                candidates.append(_rec(
                    res, "rightsize", "Over-provisioned", f"Resize {res.size} to {smaller}",
                    cost * 0.5, "high" if nonprod else "medium", "medium", stats,
                    f"Average CPU {avg:.1f}%, peak {peak:.1f}%: one size down still leaves headroom."))
        if avg > s.overused_cpu_threshold:
            return _rec(res, "overused", "Over-utilised", f"Scale up {res.size} or add instances",
                        0.0, "high", "medium", stats,
                        f"Average CPU {avg:.1f}% over {stats.days} days risks throttling and outages.")

    if nonprod and not any(c["type"] == "idle" for c in candidates):
        candidates.append(_rec(
            res, "schedule", "Runs 24/7 in non-production",
            "Stop nights and weekends (e.g. 08:00-20:00 on weekdays)",
            cost * s.offhours_saving_pct / 100, "medium", "low", stats,
            "Non-production capacity is rarely needed outside working hours."))

    if res.environment == "production" and not candidates and have_util and stats.avg >= 30:
        candidates.append(_rec(
            res, "commitment", "Steady production workload",
            "Cover with a 1-year Savings Plan / Reserved Instance / committed-use discount",
            cost * s.commitment_discount_pct / 100, "low", "medium", stats,
            f"Stable load (avg CPU {stats.avg:.1f}%) makes it a good commitment candidate."))

    return max(candidates, key=lambda c: c["estimated_monthly_savings"]) if candidates else None


def recommendations(db: Session, f: Filters, settings: Settings | None = None) -> dict:
    s = settings or get_settings()
    stats = util_stats(db, f, s.optimizer_window_days)
    stmt = apply(select(Resource), f, Resource, dates=False)
    recs = []
    for res in db.scalars(stmt):
        rec = recommend_for(res, stats.get((res.provider, res.resource_id)), s)
        if rec:
            recs.append(rec)
    recs.sort(key=lambda r: -r["estimated_monthly_savings"])

    def total(types):
        return round(sum(r["estimated_monthly_savings"] for r in recs if r["type"] in types), 2)

    quick = total(QUICK_WIN_TYPES)
    commit = total(("commitment",))
    by_type: dict[str, dict] = {}
    for r in recs:
        e = by_type.setdefault(r["type"], {"type": r["type"], "count": 0, "monthly_savings": 0.0})
        e["count"] += 1
        e["monthly_savings"] = round(e["monthly_savings"] + r["estimated_monthly_savings"], 2)
    tracked = db.scalar(apply(select(func.coalesce(func.sum(Resource.monthly_cost), 0)), f, Resource, dates=False))
    return {
        "recommendations": recs,
        "summary": {
            "quick_wins_monthly": quick, "commitment_monthly": commit,
            "total_monthly": round(quick + commit, 2), "total_annual": round((quick + commit) * 12, 2),
            "tracked_monthly_cost": round(float(tracked or 0), 2),
            "quick_wins_pct_of_tracked": round(quick / float(tracked) * 100, 1) if tracked else 0.0,
            "count": len(recs), "by_type": sorted(by_type.values(), key=lambda e: -e["monthly_savings"]),
        },
    }
