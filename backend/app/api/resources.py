from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..services import optimizer, utilization
from ..services.filters import Filters
from .deps import range_filters, scope_filters

router = APIRouter(tags=["resources"])


@router.get("/resources")
def resources(f: Filters = Depends(scope_filters), state: str | None = None, search: str | None = None,
              sort: str = Query("monthly_cost", pattern="^(monthly_cost|cpu|name)$"),
              db: Session = Depends(get_db)):
    return utilization.list_resources(db, f, state, search, sort)


@router.get("/utilization/summary")
def utilization_summary(f: Filters = Depends(scope_filters), db: Session = Depends(get_db)):
    return utilization.utilization_summary(db, f)


@router.get("/utilization/timeseries")
def utilization_timeseries(group_by: str = "provider", f: Filters = Depends(range_filters),
                           db: Session = Depends(get_db)):
    if group_by not in ("provider", "environment", "resource_type"):
        raise HTTPException(422, "group_by must be provider, environment or resource_type")
    return utilization.utilization_timeseries(db, f, group_by)


@router.get("/optimization")
def optimization(f: Filters = Depends(scope_filters), db: Session = Depends(get_db)):
    return optimizer.recommendations(db, f)
