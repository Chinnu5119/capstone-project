from datetime import date

import pytest

from app.collectors.base import ResourceRow
from app.config import get_settings
from app.models import AlertRule, Resource
from app.services import alert_engine, optimizer
from app.services.filters import Filters
from app.services.optimizer import UtilStats, recommend_for

S = get_settings()


def _res(**kw):
    base = dict(provider="aws", resource_id="i-1", name="x", service="Amazon EC2", resource_type="compute",
                size="m5.xlarge", environment="production", region="us-east-1", state="running",
                monthly_cost=140.16)
    base.update(kw)
    return Resource(**base)


def test_unattached_volume_saves_full_cost():
    r = recommend_for(_res(state="unattached", resource_type="storage", monthly_cost=40.0), None, S)
    assert r["type"] == "unattached" and r["estimated_monthly_savings"] == 40.0


def test_idle_dev_resource_is_high_confidence_full_saving():
    r = recommend_for(_res(environment="development"), UtilStats(2.0, 6.0, 14), S)
    assert (r["type"], r["confidence"], r["estimated_monthly_savings"]) == ("idle", "high", 140.16)


def test_idle_production_is_only_medium_confidence():
    assert recommend_for(_res(), UtilStats(2.0, 6.0, 14), S)["confidence"] == "medium"


def test_rightsize_saves_about_half_and_names_target():
    r = recommend_for(_res(), UtilStats(12.0, 30.0, 14), S)
    assert r["type"] == "rightsize" and "m5.large" in r["action"]
    assert r["estimated_monthly_savings"] == pytest.approx(70.08)


def test_bursty_resource_is_not_downsized():
    # low average but high peak: shrinking would hurt
    assert recommend_for(_res(), UtilStats(12.0, 90.0, 14), S) is None


def test_overused_is_risk_not_saving():
    r = recommend_for(_res(), UtilStats(92.0, 99.0, 14), S)
    assert r["type"] == "overused" and r["estimated_monthly_savings"] == 0.0


def test_nonprod_gets_schedule_but_idle_wins_over_schedule():
    sched = recommend_for(_res(environment="staging"), UtilStats(40.0, 70.0, 14), S)
    assert sched["type"] == "schedule"
    assert sched["estimated_monthly_savings"] == pytest.approx(140.16 * 0.64, abs=0.01)
    assert recommend_for(_res(environment="staging"), UtilStats(1.0, 4.0, 14), S)["type"] == "idle"


def test_steady_production_gets_commitment_but_light_load_does_not():
    r = recommend_for(_res(), UtilStats(55.0, 80.0, 14), S)
    assert r["type"] == "commitment" and r["estimated_monthly_savings"] == pytest.approx(140.16 * 0.3, abs=0.01)
    assert recommend_for(_res(), UtilStats(25.0, 80.0, 14), S) is None


def test_too_little_history_makes_no_utilisation_claims():
    assert recommend_for(_res(), UtilStats(1.0, 2.0, 2), S) is None
    assert recommend_for(_res(), None, S) is None


def test_non_compute_resources_are_ignored():
    assert recommend_for(_res(resource_type="storage", service="Amazon S3"), UtilStats(1, 1, 14), S) is None


def test_one_recommendation_per_resource_and_totals_consistent(mock_db):
    out = optimizer.recommendations(mock_db, Filters())
    ids = [r["id"] for r in out["recommendations"]]
    assert len(ids) == len(set(ids))
    keys = {(r["provider"], r["resource_id"]) for r in out["recommendations"]}
    assert len(keys) == len(out["recommendations"])
    s = out["summary"]
    assert s["total_monthly"] == pytest.approx(s["quick_wins_monthly"] + s["commitment_monthly"], abs=0.01)
    assert s["total_annual"] == pytest.approx(s["total_monthly"] * 12, abs=0.1)
    assert sum(t["monthly_savings"] for t in s["by_type"]) == pytest.approx(s["total_monthly"], abs=0.05)
    # savings of any recommendation can never exceed what the resource costs
    assert all(r["estimated_monthly_savings"] <= r["monthly_cost"] + 0.01 for r in out["recommendations"])
    assert 0 < s["quick_wins_pct_of_tracked"] < 100


def test_mock_data_surfaces_every_recommendation_type(mock_db):
    types = {r["type"] for r in optimizer.recommendations(mock_db, Filters())["recommendations"]}
    assert types == {"unattached", "idle", "rightsize", "schedule", "commitment", "overused"}


def test_optimizer_respects_scope_filters(mock_db):
    out = optimizer.recommendations(mock_db, Filters(provider="gcp", environment="development"))
    assert out["recommendations"]
    assert all(r["provider"] == "gcp" and r["environment"] == "development" for r in out["recommendations"])


# ----------------------------------------------------------------------- alert rules
def _rule(db, **kw):
    base = dict(name="r", rule_type="daily_cost", threshold=100.0, severity="warning")
    base.update(kw)
    rule = AlertRule(**base)
    db.add(rule)
    db.commit()
    return rule


def test_daily_cost_rule_breaches_and_scopes(mock_db):
    total = alert_engine.evaluate_rule(mock_db, _rule(mock_db, threshold=100))
    assert total.breached and 300 < total.value < 600
    aws = alert_engine.evaluate_rule(mock_db, _rule(mock_db, provider="aws", threshold=100))
    assert aws.value < total.value
    assert not alert_engine.evaluate_rule(mock_db, _rule(mock_db, threshold=10_000)).breached


def test_threshold_is_strictly_greater_than(mock_db):
    v = alert_engine.evaluate_rule(mock_db, _rule(mock_db, threshold=0)).value
    assert not alert_engine.evaluate_rule(mock_db, _rule(mock_db, threshold=v)).breached


def test_every_rule_type_evaluates(mock_db):
    for rtype in alert_engine.RULE_TYPES:
        res = alert_engine.evaluate_rule(mock_db, _rule(mock_db, rule_type=rtype, threshold=1))
        assert isinstance(res.value, float) and res.detail, rtype


def test_cost_spike_rule_sees_gcp_bigquery_spike(mock_db):
    res = alert_engine.evaluate_rule(mock_db, _rule(mock_db, rule_type="cost_spike_pct", provider="gcp", threshold=15))
    assert res.breached and res.value > 15


def test_cpu_rule_names_hottest_resource(mock_db):
    res = alert_engine.evaluate_rule(mock_db, _rule(mock_db, rule_type="cpu_high", threshold=50))
    assert res.breached and res.value > 80 and "CPU" in res.detail


def test_idle_count_rule(mock_db):
    res = alert_engine.evaluate_rule(mock_db, _rule(mock_db, rule_type="idle_resource_count", threshold=2))
    assert res.breached and res.value == 5.0


def test_rule_on_empty_database_does_not_crash(db):
    for rtype in alert_engine.RULE_TYPES:
        res = alert_engine.evaluate_rule(db, _rule(db, rule_type=rtype, threshold=1))
        assert res.value == 0.0 and not res.breached


def test_default_rules_seed_once(db):
    assert alert_engine.seed_default_rules(db) == len(alert_engine.DEFAULT_RULES)
    assert alert_engine.seed_default_rules(db) == 0
