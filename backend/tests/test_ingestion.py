from datetime import date

from sqlalchemy import func, select

from app.collectors.base import BaseCollector, CostRow, ResourceRow
from app.collectors.mock import MockCollector
from app.config import get_settings
from app.models import CollectionRun, CostRecord, Resource, UtilizationRecord
from app.services import ingestion

TODAY = date(2026, 10, 30)


def _count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def test_collection_is_idempotent(db):
    settings = get_settings()
    collector = MockCollector("aws", today=TODAY)
    for _ in range(2):
        run = ingestion.collect_provider(db, "aws", settings=settings, collector=collector)
        assert run.status == "success"
    first = (_count(db, CostRecord), _count(db, Resource), _count(db, UtilizationRecord))
    ingestion.collect_provider(db, "aws", settings=settings, collector=collector)
    assert first == (_count(db, CostRecord), _count(db, Resource), _count(db, UtilizationRecord))
    assert first[0] > 0 and first[1] > 0 and first[2] > 0
    # unique key really holds: no duplicate (date, service, env, region) rows
    dupes = db.execute(select(CostRecord.date, CostRecord.service, CostRecord.environment, CostRecord.region,
                              func.count()).group_by(CostRecord.date, CostRecord.service,
                                                     CostRecord.environment, CostRecord.region)
                       .having(func.count() > 1)).all()
    assert dupes == []


def test_first_run_backfills_then_lookback_only(db):
    s = get_settings()
    (c_start, c_end), _ = ingestion.collection_windows(db, "gcp", "mock", s, today=TODAY)
    assert (c_end - c_start).days + 1 == s.mock_history_days
    ingestion.ingest_costs(db, "gcp", [CostRow(c_end, "gcp", "BigQuery", "other", "production", 1.0)], c_start, c_end)
    (c_start2, _), _ = ingestion.collection_windows(db, "gcp", "mock", s, today=TODAY)
    assert (c_end - c_start2).days + 1 == s.cost_lookback_days


def test_duplicate_keys_are_summed_and_window_replaced(db):
    d = date(2026, 10, 1)
    rows = [CostRow(d, "aws", "Amazon EC2", "compute", "production", 10.0, account="a"),
            CostRow(d, "aws", "Amazon EC2", "compute", "production", 5.5, account="a")]
    assert ingestion.ingest_costs(db, "aws", rows, d, d) == 1
    assert db.scalar(select(CostRecord.cost)) == 15.5
    # re-ingesting a revised figure replaces it, it does not add to it
    ingestion.ingest_costs(db, "aws", [CostRow(d, "aws", "Amazon EC2", "compute", "production", 9.0, account="a")], d, d)
    assert db.scalar(select(CostRecord.cost)) == 9.0
    # other providers are untouched by a provider-scoped replace
    ingestion.ingest_costs(db, "azure", [CostRow(d, "azure", "Virtual Machines", "compute", "production", 3.0)], d, d)
    ingestion.ingest_costs(db, "aws", [], d, d)
    assert _count(db, CostRecord) == 1


def test_stale_resources_are_removed(db):
    def row(rid):
        return ResourceRow("aws", rid, rid, "Amazon EC2", "compute", "m5.large", "production", "us-east-1",
                           "running", 70.0, cpu_pct=10)
    ingestion.ingest_resources(db, "aws", [row("a"), row("b")])
    ingestion.ingest_resources(db, "aws", [row("a")])
    assert [r.resource_id for r in db.scalars(select(Resource))] == ["a"]


class _Flaky(BaseCollector):
    provider, mode = "aws", "live"

    def check_connection(self):
        return True, ""

    def fetch_resources(self):
        return []

    def fetch_costs(self, start, end):
        raise RuntimeError("AccessDenied: ce:GetCostAndUsage")

    def fetch_utilization(self, start, end):
        return []


def test_failing_step_is_recorded_and_others_still_run(db):
    run = ingestion.collect_provider(db, "aws", settings=get_settings(), collector=_Flaky())
    assert run.status == "partial"
    assert "AccessDenied" in run.error and run.error.startswith("costs:")
    assert db.get(CollectionRun, run.id).finished_at is not None
