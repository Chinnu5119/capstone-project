from datetime import date, timedelta

import pytest
from sqlalchemy import func, select

from app.models import CostRecord
from app.services import analytics
from app.services.filters import Filters, resolve_range

TODAY = date(2026, 10, 30)
LATEST = TODAY - timedelta(days=1)


def _f(db, **kw):
    s, e = resolve_range(db, None, None, kw.pop("days", 30))
    return Filters(start=s, end=e, **kw)


def test_summary_matches_raw_sql(mock_db):
    f = _f(mock_db)
    s = analytics.summary(mock_db, f)
    raw = mock_db.scalar(select(func.sum(CostRecord.cost)).where(CostRecord.date >= f.start, CostRecord.date <= f.end))
    assert s["total_cost"] == pytest.approx(raw, abs=0.01)
    assert s["end"] == LATEST.isoformat() and s["days"] == 30
    assert s["avg_daily_cost"] == pytest.approx(raw / 30, abs=0.01)


def test_breakdowns_add_up_to_total(mock_db):
    f = _f(mock_db)
    total = analytics.cost_total(mock_db, f)
    for dim in ("provider", "service", "environment", "resource_type", "region"):
        parts = analytics.cost_breakdown(mock_db, f, dim)
        assert sum(p["cost"] for p in parts) == pytest.approx(total, abs=0.05 * len(parts))
        assert sum(p["share_pct"] for p in parts) == pytest.approx(100, abs=0.5)


def test_filters_narrow_results(mock_db):
    all_cost = analytics.cost_total(mock_db, _f(mock_db))
    aws = analytics.cost_total(mock_db, _f(mock_db, provider="aws"))
    aws_prod = analytics.cost_total(mock_db, _f(mock_db, provider="aws", environment="production"))
    aws_prod_db = analytics.cost_total(mock_db, _f(mock_db, provider="aws", environment="production", resource_type="database"))
    assert all_cost > aws > aws_prod > aws_prod_db > 0
    providers = {p["key"] for p in analytics.cost_breakdown(mock_db, _f(mock_db, provider="gcp"), "provider")}
    assert providers == {"gcp"}


def test_timeseries_is_dense_and_consistent(mock_db):
    f = _f(mock_db, days=14)
    ts = analytics.cost_timeseries(mock_db, f, "provider")
    assert len(ts["data"]) == 14
    assert set(ts["series"]) == {"aws", "azure", "gcp"}
    for point in ts["data"]:
        assert point["total"] == pytest.approx(sum(point[s] for s in ts["series"]), abs=0.05)
    assert sum(p["total"] for p in ts["data"]) == pytest.approx(analytics.cost_total(mock_db, f), abs=0.5)


def test_timeseries_groups_overflow_into_other(mock_db):
    ts = analytics.cost_timeseries(mock_db, _f(mock_db, days=7), "service", top_n=3)
    assert len(ts["series"]) == 4 and ts["series"][-1] == "Other"
    assert ts["data"][0]["total"] == pytest.approx(sum(ts["data"][0][s] for s in ts["series"]), abs=0.05)


def test_forecast_is_mtd_plus_run_rate(mock_db):
    fc = analytics.month_forecast(mock_db, Filters(), LATEST)       # Oct 29 -> 2 days remain
    assert fc["days_remaining"] == 2 and fc["days_in_month"] == 31
    assert fc["projected_month_end"] == pytest.approx(fc["month_to_date"] + 2 * fc["daily_run_rate"], abs=0.05)
    first = analytics.month_forecast(mock_db, Filters(), date(2026, 10, 1))
    assert first["month_to_date"] == pytest.approx(first["daily_run_rate"], rel=0.2)


def test_monthly_marks_partial_and_compares_per_day(mock_db):
    months = analytics.monthly_costs(mock_db, Filters(), months=3)
    assert [m["month"] for m in months] == ["2026-08", "2026-09", "2026-10"]
    assert months[-1]["partial"] is True and months[1]["partial"] is False
    sep, octo = months[1], months[2]
    expected = (octo["avg_daily"] - sep["avg_daily"]) / sep["avg_daily"] * 100
    assert octo["mom_change_pct"] == pytest.approx(expected, abs=0.1)
    assert abs(octo["mom_change_pct"]) < 15      # a partial month is not reported as a ~-5% collapse


def test_anomaly_detection_finds_injected_spikes_without_noise(mock_db):
    found = analytics.detect_anomalies(mock_db, Filters(end=LATEST))
    keys = {(a["provider"], a["service"], a["environment"], a["date"]) for a in found}
    assert ("aws", "Amazon EC2", "production", (LATEST - timedelta(days=2)).isoformat()) in keys
    assert ("gcp", "BigQuery", "production", LATEST.isoformat()) in keys
    assert len(found) == 2, found                  # ordinary noise and weekends do not alert
    assert all(a["severity"] == "critical" for a in found)


def test_anomaly_detection_ignores_weekly_pattern_and_small_amounts(db):
    from app.collectors.base import CostRow
    from app.services import ingestion

    start = date(2026, 9, 1)
    rows = []
    for i in range(45):
        d = start + timedelta(days=i)
        rows.append(CostRow(d, "aws", "Amazon EC2", "compute", "production", 100 * (0.85 if d.weekday() >= 5 else 1)))
        rows.append(CostRow(d, "aws", "AWS Lambda", "compute", "production", 0.5 if i < 44 else 3.0))  # tiny: below $ bar
    ingestion.ingest_costs(db, "aws", rows, start, start + timedelta(days=44))
    assert analytics.detect_anomalies(db, Filters(end=start + timedelta(days=44))) == []
