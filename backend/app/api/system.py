from __future__ import annotations

import threading

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import __version__
from ..collectors import get_collector
from ..config import PROVIDERS, get_settings
from ..db import SessionLocal, get_db
from ..models import CollectionRun
from ..services import ingestion

router = APIRouter(tags=["system"])
_collect_lock = threading.Lock()


class CollectRequest(BaseModel):
    provider: str | None = None
    kinds: list[str] | None = None


@router.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(select(1))
    return {"status": "ok", "version": __version__}


@router.get("/providers/status")
def providers_status(db: Session = Depends(get_db)):
    return ingestion.provider_status(db)


@router.post("/providers/{provider}/test")
def test_connection(provider: str):
    """Verify credentials/connectivity for one provider."""
    if provider not in PROVIDERS:
        raise HTTPException(404, "Unknown provider")
    collector = get_collector(provider, get_settings())
    if collector is None:
        return {"provider": provider, "mode": "disabled", "ok": False, "detail": "Provider is disabled"}
    ok, detail = collector.check_connection()
    return {"provider": provider, "mode": collector.mode, "ok": ok, "detail": detail}


def _run(provider: str | None, kinds: tuple[str, ...]):
    try:
        with SessionLocal() as db:
            ingestion.collect_all(db, kinds=kinds, providers=[provider] if provider else None)
    finally:
        _collect_lock.release()


@router.post("/collect", status_code=202)
def collect_now(body: CollectRequest, background: BackgroundTasks):
    """Trigger a collection in the background (poll /collection/runs for the result)."""
    if body.provider and body.provider not in PROVIDERS:
        raise HTTPException(422, "Unknown provider")
    kinds = tuple(body.kinds or ingestion.ALL_KINDS)
    if not set(kinds) <= set(ingestion.ALL_KINDS):
        raise HTTPException(422, f"kinds must be a subset of {ingestion.ALL_KINDS}")
    if not _collect_lock.acquire(blocking=False):
        raise HTTPException(409, "A collection is already running")
    background.add_task(_run, body.provider, kinds)
    return {"status": "started", "provider": body.provider or "all", "kinds": kinds}


@router.get("/collection/runs")
def runs(limit: int = Query(20, ge=1, le=200), db: Session = Depends(get_db)):
    rows = db.scalars(select(CollectionRun).order_by(CollectionRun.id.desc()).limit(limit))
    return [{
        "id": r.id, "provider": r.provider, "mode": r.mode, "kinds": r.kinds, "status": r.status,
        "started_at": r.started_at.isoformat() + "Z",
        "finished_at": r.finished_at.isoformat() + "Z" if r.finished_at else None,
        "cost_rows": r.cost_rows, "resource_rows": r.resource_rows, "util_rows": r.util_rows,
        "error": r.error,
    } for r in rows]
