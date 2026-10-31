"""FastAPI application entrypoint."""
from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .api import api_router
from .config import get_settings
from .db import SessionLocal, init_db
from .metrics import render_metrics
from .scheduler import bootstrap, start_scheduler
from .services.alert_engine import seed_default_rules

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    init_db()
    with SessionLocal() as db:
        seeded = seed_default_rules(db)
        if seeded:
            log.info("Seeded %d default alert rules", seeded)
    log.info("Provider modes: %s", settings.provider_modes())
    scheduler = start_scheduler(settings) if settings.scheduler_enabled else None
    if settings.seed_on_startup:
        # run in a thread so the API (and /health) is available immediately
        threading.Thread(target=bootstrap, name="bootstrap", daemon=True).start()
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(
    title="DevOps Dashboard for Resource and Cost Monitoring",
    version=__version__,
    description="Aggregates AWS, Azure and GCP cost and utilisation data; exposes Prometheus metrics.",
    lifespan=lifespan,
)
_origins = [o.strip() for o in get_settings().cors_origins.split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_methods=["*"], allow_headers=["*"])
app.include_router(api_router)


@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    body, content_type = render_metrics()
    return Response(content=body, media_type=content_type)
