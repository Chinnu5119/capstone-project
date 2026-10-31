from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import CostRecord
from ..normalize import ENVIRONMENTS, RESOURCE_TYPES
from ..services import analytics
from ..services.filters import Filters
from .deps import range_filters

router = APIRouter(tags=["costs"])


def _group(group_by: str) -> str:
    if group_by not in analytics.GROUP_COLUMNS and group_by != "none":
        raise HTTPException(422, f"group_by must be one of {', '.join([*analytics.GROUP_COLUMNS, 'none'])}")
    return group_by


@router.get("/filters")
def filter_options(db: Session = Depends(get_db)):
    """Values that populate the dashboard's filter bar, plus the span of available data."""
    lo, hi = db.execute(select(func.min(CostRecord.date), func.max(CostRecord.date))).one()
    present = lambda col: [v for (v,) in db.execute(select(col).distinct().order_by(col))]  # noqa: E731
    return {
        "providers": present(CostRecord.provider),
        "environments": [e for e in ENVIRONMENTS if e in present(CostRecord.environment)],
        "resource_types": [t for t in RESOURCE_TYPES if t in present(CostRecord.resource_type)],
        "services": present(CostRecord.service),
        "regions": present(CostRecord.region),
        "first_date": lo.isoformat() if lo else None,
        "last_date": hi.isoformat() if hi else None,
    }


@router.get("/costs/summary")
def cost_summary(f: Filters = Depends(range_filters), db: Session = Depends(get_db)):
    return analytics.summary(db, f)


@router.get("/costs/timeseries")
def cost_timeseries(group_by: str = "provider", top_n: int = Query(8, ge=1, le=20),
                    f: Filters = Depends(range_filters), db: Session = Depends(get_db)):
    return analytics.cost_timeseries(db, f, _group(group_by), top_n)


@router.get("/costs/breakdown")
def cost_breakdown(group_by: str = "provider", f: Filters = Depends(range_filters),
                   db: Session = Depends(get_db)):
    if _group(group_by) == "none":
        raise HTTPException(422, "group_by 'none' is not valid for a breakdown")
    return analytics.cost_breakdown(db, f, group_by)


@router.get("/costs/monthly")
def monthly(months: int = Query(6, ge=2, le=24), f: Filters = Depends(range_filters),
            db: Session = Depends(get_db)):
    return analytics.monthly_costs(db, f, months)


@router.get("/costs/anomalies")
def anomalies(f: Filters = Depends(range_filters), recent_days: int = Query(7, ge=1, le=30),
              db: Session = Depends(get_db)):
    return analytics.detect_anomalies(db, f, recent_days=recent_days)
