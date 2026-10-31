import os
import tempfile
from datetime import date

import pytest

# Must be set before the app is imported: settings are read once.
_tmpdir = tempfile.mkdtemp(prefix="dash-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmpdir}/test.db"
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["SEED_ON_STARTUP"] = "false"
for p in ("AWS", "AZURE", "GCP"):
    os.environ[f"{p}_MODE"] = "mock"
os.environ["SLACK_WEBHOOK_URL"] = ""
os.environ["TEAMS_WEBHOOK_URL"] = ""
os.environ["WEBHOOK_TOKEN"] = ""

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.models import Base  # noqa: E402

FIXED_TODAY = date(2026, 10, 30)


@pytest.fixture()
def db():
    """Isolated in-memory database per test."""
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        yield session
    engine.dispose()


@pytest.fixture()
def mock_db(db):
    """In-memory DB filled by the deterministic mock collectors (clock fixed)."""
    from app.collectors.mock import MockCollector
    from app.config import get_settings
    from app.services import ingestion

    settings = get_settings()
    for provider in ("aws", "azure", "gcp"):
        collector = MockCollector(provider, today=FIXED_TODAY)
        cost_win, util_win = ingestion.collection_windows(db, provider, "mock", settings, today=FIXED_TODAY)
        ingestion.ingest_resources(db, provider, collector.fetch_resources())
        ingestion.ingest_costs(db, provider, collector.fetch_costs(*cost_win), *cost_win)
        ingestion.ingest_utilization(db, provider, collector.fetch_utilization(*util_win), *util_win)
    return db


@pytest.fixture(scope="session")
def client():
    """HTTP client against the real app with a seeded file database."""
    from fastapi.testclient import TestClient

    from app.db import SessionLocal
    from app.main import app
    from app.services.ingestion import collect_all

    with TestClient(app) as c:
        with SessionLocal() as session:
            collect_all(session)
        yield c
