"""Background jobs: periodic collection of resources (frequent) and costs (slower).

Run the API with a single worker process: jobs live inside the app process, so several
workers would each run every job.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from .config import Settings, get_settings
from .db import SessionLocal
from .services.ingestion import collect_all

log = logging.getLogger(__name__)


def _job(kinds: tuple[str, ...]):
    def run():
        with SessionLocal() as db:
            collect_all(db, kinds=kinds)
    run.__name__ = f"collect_{'_'.join(kinds)}"
    return run


def bootstrap() -> None:
    """Initial full collection (backfills history on first start)."""
    log.info("Bootstrap collection started")
    with SessionLocal() as db:
        runs = collect_all(db)
    log.info("Bootstrap collection finished: %s", [(r.provider, r.status) for r in runs])


def start_scheduler(settings: Settings | None = None) -> BackgroundScheduler:
    s = settings or get_settings()
    sched = BackgroundScheduler(timezone="UTC")
    sched.add_job(_job(("resources",)), "interval", minutes=s.resource_collection_interval_minutes,
                  id="resources", max_instances=1, coalesce=True)
    sched.add_job(_job(("costs", "utilization")), "interval", minutes=s.cost_collection_interval_minutes,
                  id="costs", max_instances=1, coalesce=True)
    sched.start()
    return sched
