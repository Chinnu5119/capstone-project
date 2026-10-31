"""Shared request parsing: validated filter parameters -> Filters."""
from __future__ import annotations

from datetime import date

from fastapi import Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..config import PROVIDERS
from ..db import get_db
from ..normalize import ENVIRONMENTS, RESOURCE_TYPES
from ..services.filters import Filters, resolve_range


def _clean(value: str | None, allowed: tuple[str, ...], name: str) -> str | None:
    if value is None or value.strip().lower() in ("", "all"):
        return None
    v = value.strip().lower()
    if v not in allowed:
        raise HTTPException(422, f"Invalid {name} {value!r}; expected one of {', '.join(allowed)} or 'all'")
    return v


def scope_filters(
    provider: str | None = Query(None, description="aws | azure | gcp | all"),
    environment: str | None = Query(None, description="production | staging | development | untagged | all"),
    resource_type: str | None = Query(None, description="compute | database | storage | network | other | all"),
) -> Filters:
    """Filters without a date window (inventory, optimisation, alert scope)."""
    return Filters(
        provider=_clean(provider, PROVIDERS, "provider"),
        environment=_clean(environment, ENVIRONMENTS, "environment"),
        resource_type=_clean(resource_type, RESOURCE_TYPES, "resource_type"),
    )


def range_filters(
    scope: Filters = Depends(scope_filters),
    start: date | None = Query(None),
    end: date | None = Query(None),
    days: int | None = Query(None, ge=1, le=730, description="Window length when start is omitted (default 30)"),
    db: Session = Depends(get_db),
) -> Filters:
    s, e = resolve_range(db, start, end, days)
    return Filters(scope.provider, scope.environment, scope.resource_type, s, e)
