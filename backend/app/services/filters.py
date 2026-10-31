"""Shared filter object and SQL helpers used by analytics, optimiser and alert engine."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import CostRecord


@dataclass(frozen=True)
class Filters:
    provider: str | None = None
    environment: str | None = None
    resource_type: str | None = None
    start: date | None = None
    end: date | None = None


def apply(stmt, f: Filters, model, dates: bool = True):
    """Add provider/environment/resource_type (and optionally date) predicates to a statement."""
    if f.provider:
        stmt = stmt.where(model.provider == f.provider)
    if f.environment:
        stmt = stmt.where(model.environment == f.environment)
    if f.resource_type:
        stmt = stmt.where(model.resource_type == f.resource_type)
    if dates and hasattr(model, "date"):
        if f.start:
            stmt = stmt.where(model.date >= f.start)
        if f.end:
            stmt = stmt.where(model.date <= f.end)
    return stmt


def latest_cost_date(db: Session) -> date | None:
    return db.scalar(select(func.max(CostRecord.date)))


def resolve_range(db: Session, start: date | None, end: date | None, days: int | None) -> tuple[date, date]:
    """Default window = the last `days` (30) ending at the newest day we have data for."""
    latest = latest_cost_date(db) or (date.today() - timedelta(days=1))
    end = end or latest
    start = start or end - timedelta(days=(days or 30) - 1)
    if start > end:
        start, end = end, start
    return start, end


def daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)
