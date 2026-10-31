"""Cost analytics: totals, trends, breakdowns, monthly comparison, forecast and anomalies."""
from __future__ import annotations

import calendar
import statistics
from collections import defaultdict
from dataclasses import replace
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import CostRecord
from .filters import Filters, apply, daterange, latest_cost_date

GROUP_COLUMNS = {
    "provider": CostRecord.provider,
    "service": CostRecord.service,
    "environment": CostRecord.environment,
    "resource_type": CostRecord.resource_type,
    "region": CostRecord.region,
}


def _r(x: float, nd: int = 2) -> float:
    return round(float(x or 0), nd)


def cost_total(db: Session, f: Filters) -> float:
    stmt = apply(select(func.coalesce(func.sum(CostRecord.cost), 0)), f, CostRecord)
    return float(db.scalar(stmt) or 0)


# --------------------------------------------------------------------------- forecast
def month_forecast(db: Session, f: Filters, as_of: date) -> dict:
    """Month-end projection = month-to-date + (trailing 7-day average x days remaining)."""
    month_start = as_of.replace(day=1)
    days_in_month = calendar.monthrange(as_of.year, as_of.month)[1]
    scope = replace(f, start=None, end=None)
    mtd = cost_total(db, replace(scope, start=month_start, end=as_of))
    t0 = as_of - timedelta(days=6)
    stmt = apply(select(func.coalesce(func.sum(CostRecord.cost), 0), func.count(func.distinct(CostRecord.date))),
                 replace(scope, start=t0, end=as_of), CostRecord)
    recent_total, recent_days = db.execute(stmt).one()
    run_rate = float(recent_total or 0) / recent_days if recent_days else 0.0
    remaining = days_in_month - as_of.day
    return {
        "as_of": as_of.isoformat(), "month_to_date": _r(mtd), "daily_run_rate": _r(run_rate),
        "days_remaining": remaining, "days_in_month": days_in_month,
        "projected_month_end": _r(mtd + run_rate * remaining),
    }


# --------------------------------------------------------------------------- summary
def summary(db: Session, f: Filters) -> dict:
    assert f.start and f.end
    total = cost_total(db, f)
    days = (f.end - f.start).days + 1
    prev_end = f.start - timedelta(days=1)
    prev = cost_total(db, replace(f, start=prev_end - timedelta(days=days - 1), end=prev_end))
    fc = month_forecast(db, f, f.end)

    top_stmt = apply(select(CostRecord.service, func.sum(CostRecord.cost).label("c")), f, CostRecord)
    top = db.execute(top_stmt.group_by(CostRecord.service).order_by(func.sum(CostRecord.cost).desc()).limit(1)).first()
    last_day = cost_total(db, replace(f, start=f.end, end=f.end))
    return {
        "start": f.start.isoformat(), "end": f.end.isoformat(), "days": days,
        "total_cost": _r(total), "previous_period_cost": _r(prev),
        "change_pct": _r((total - prev) / prev * 100, 1) if prev else None,
        "avg_daily_cost": _r(total / days), "latest_day_cost": _r(last_day),
        "top_service": {"name": top[0], "cost": _r(top[1])} if top else None,
        **fc,
    }


# --------------------------------------------------------------------------- trends
def cost_timeseries(db: Session, f: Filters, group_by: str = "provider", top_n: int = 8) -> dict:
    """Daily cost, pivoted for charting: {series: [...], data: [{date, <series>: cost}]}."""
    assert f.start and f.end
    if group_by == "none":
        stmt = apply(select(CostRecord.date, func.sum(CostRecord.cost)), f, CostRecord).group_by(CostRecord.date)
        rows = [(d, "total", c) for d, c in db.execute(stmt)]
    else:
        col = GROUP_COLUMNS[group_by]
        stmt = apply(select(CostRecord.date, col, func.sum(CostRecord.cost)), f, CostRecord).group_by(CostRecord.date, col)
        rows = list(db.execute(stmt))

    totals: dict[str, float] = defaultdict(float)
    for _d, k, c in rows:
        totals[k] += float(c)
    ranked = [k for k, _ in sorted(totals.items(), key=lambda kv: -kv[1])]
    keep = ranked[:top_n]
    overflow = len(ranked) > top_n
    series = keep + (["Other"] if overflow else [])

    by_day: dict[date, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for d, k, c in rows:
        by_day[d][k if k in keep else "Other"] += float(c)
    data = []
    for d in daterange(f.start, f.end):
        point = {"date": d.isoformat(), **{s: _r(by_day[d].get(s, 0)) for s in series}}
        point["total"] = _r(sum(by_day[d].values()))
        data.append(point)
    return {"group_by": group_by, "series": series, "data": data}


def cost_breakdown(db: Session, f: Filters, group_by: str = "provider") -> list[dict]:
    col = GROUP_COLUMNS[group_by]
    stmt = apply(select(col, func.sum(CostRecord.cost).label("c")), f, CostRecord)
    rows = db.execute(stmt.group_by(col).order_by(func.sum(CostRecord.cost).desc())).all()
    total = sum(float(c) for _k, c in rows)
    return [{"key": k, "cost": _r(c), "share_pct": _r(float(c) / total * 100, 1) if total else 0.0}
            for k, c in rows]


# --------------------------------------------------------------------------- monthly
def monthly_costs(db: Session, f: Filters, months: int = 6) -> list[dict]:
    """Monthly totals with month-over-month change; the in-progress month is flagged partial."""
    latest = latest_cost_date(db)
    if latest is None:
        return []
    y, m = latest.year, latest.month - (months - 1)
    while m < 1:
        m, y = m + 12, y - 1
    first = date(y, m, 1)
    stmt = apply(select(CostRecord.date, CostRecord.provider, func.sum(CostRecord.cost)),
                 replace(f, start=first, end=latest), CostRecord)
    per: dict[str, dict] = {}
    days_seen: dict[str, set[date]] = defaultdict(set)
    for d, provider, c in db.execute(stmt.group_by(CostRecord.date, CostRecord.provider)):
        key = f"{d.year:04d}-{d.month:02d}"
        entry = per.setdefault(key, {"month": key, "total": 0.0, "by_provider": defaultdict(float)})
        entry["total"] += float(c)
        entry["by_provider"][provider] += float(c)
        days_seen[key].add(d)
    out, prev_daily = [], None
    for key in sorted(per):
        e = per[key]
        y, mo = int(key[:4]), int(key[5:])
        n_days = len(days_seen[key])
        partial = n_days < calendar.monthrange(y, mo)[1]
        daily = e["total"] / n_days
        out.append({
            "month": key, "total": _r(e["total"]), "avg_daily": _r(daily),
            "by_provider": {p: _r(v) for p, v in sorted(e["by_provider"].items())},
            "days_with_data": n_days, "partial": partial,
            # compared on average spend per day so partial and 28/31-day months stay comparable
            "mom_change_pct": _r((daily - prev_daily) / prev_daily * 100, 1) if prev_daily else None,
        })
        prev_daily = daily
    return out


# --------------------------------------------------------------------------- anomalies
def detect_anomalies(db: Session, f: Filters, recent_days: int = 7, baseline_days: int = 14,
                     min_abs: float = 10.0, min_pct: float = 25.0, z_cut: float = 3.5) -> list[dict]:
    """Flag days whose spend for a (provider, service, environment) is far above its baseline.

    Robust to outliers: baseline = median of the preceding `baseline_days`; spread = MAD.
    A point must beat BOTH the statistical bar (modified z-score) and practical bars
    (>= min_pct above baseline and >= min_abs dollars) to avoid noisy alerts.
    """
    end = f.end or latest_cost_date(db)
    if end is None:
        return []
    start = end - timedelta(days=recent_days + baseline_days)
    stmt = apply(select(CostRecord.date, CostRecord.provider, CostRecord.service, CostRecord.environment,
                        func.sum(CostRecord.cost)), replace(f, start=start, end=end), CostRecord)
    series: dict[tuple, dict[date, float]] = defaultdict(dict)
    for d, p, s, e, c in db.execute(stmt.group_by(CostRecord.date, CostRecord.provider, CostRecord.service,
                                                  CostRecord.environment)):
        series[(p, s, e)][d] = float(c)

    found = []
    for (p, s, e), by_day in series.items():
        for offset in range(recent_days):
            day = end - timedelta(days=offset)
            if day not in by_day:
                continue
            base = [by_day[day - timedelta(days=i)] for i in range(1, baseline_days + 1)
                    if (day - timedelta(days=i)) in by_day]
            if len(base) < 7:
                continue
            med = statistics.median(base)
            mad = statistics.median(abs(x - med) for x in base)
            mad = max(mad, 0.03 * med, 0.01)  # floor so flat series do not explode the score
            value = by_day[day]
            z = 0.6745 * (value - med) / mad
            delta = value - med
            pct = delta / med * 100 if med else 0.0
            if z >= z_cut and pct >= min_pct and delta >= min_abs:
                found.append({
                    "date": day.isoformat(), "provider": p, "service": s, "environment": e,
                    "cost": _r(value), "expected": _r(med), "delta": _r(delta), "pct_over": _r(pct, 1),
                    "severity": "critical" if pct >= 100 else "warning",
                })
    found.sort(key=lambda a: (a["date"], a["delta"]), reverse=True)
    return found
