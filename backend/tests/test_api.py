import pytest


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_filter_options(client):
    j = client.get("/api/filters").json()
    assert j["providers"] == ["aws", "azure", "gcp"]
    assert set(j["environments"]) == {"production", "staging", "development"}
    assert {"compute", "database", "storage"} <= set(j["resource_types"])
    assert j["first_date"] < j["last_date"]


def test_summary_and_filters_combine(client):
    all_ = client.get("/api/costs/summary").json()
    aws = client.get("/api/costs/summary", params={"provider": "aws"}).json()
    prod_db = client.get("/api/costs/summary", params={"provider": "aws", "environment": "production",
                                                      "resource_type": "database"}).json()
    assert all_["total_cost"] > aws["total_cost"] > prod_db["total_cost"] > 0
    assert client.get("/api/costs/summary", params={"provider": "all"}).json()["total_cost"] == all_["total_cost"]


def test_date_range_parameters(client):
    j = client.get("/api/costs/summary", params={"start": "2026-10-01", "end": "2026-10-07"}).json()
    assert (j["start"], j["end"], j["days"]) == ("2026-10-01", "2026-10-07", 7)
    swapped = client.get("/api/costs/summary", params={"start": "2026-10-07", "end": "2026-10-01"}).json()
    assert swapped["total_cost"] == j["total_cost"]


@pytest.mark.parametrize("params", [{"provider": "oracle"}, {"environment": "prodd"}, {"resource_type": "gpu"}])
def test_invalid_filters_are_rejected(client, params):
    assert client.get("/api/costs/summary", params=params).status_code == 422


def test_invalid_group_by_rejected(client):
    assert client.get("/api/costs/timeseries", params={"group_by": "bogus"}).status_code == 422
    assert client.get("/api/costs/breakdown", params={"group_by": "none"}).status_code == 422


def test_timeseries_and_breakdown_shapes(client):
    ts = client.get("/api/costs/timeseries", params={"days": 10, "group_by": "environment"}).json()
    assert len(ts["data"]) == 10 and "production" in ts["series"]
    bd = client.get("/api/costs/breakdown", params={"group_by": "service"}).json()
    assert bd == sorted(bd, key=lambda x: -x["cost"])


def test_monthly_and_anomalies(client):
    months = client.get("/api/costs/monthly", params={"months": 4}).json()
    assert len(months) == 4 and months[0]["mom_change_pct"] is None
    assert len(client.get("/api/costs/anomalies").json()) >= 1


def test_resources_filter_and_search(client):
    allr = client.get("/api/resources").json()
    gcp = client.get("/api/resources", params={"provider": "gcp"}).json()
    assert len(allr) > len(gcp) > 0 and all(r["provider"] == "gcp" for r in gcp)
    assert [r["name"] for r in client.get("/api/resources", params={"search": "orphan"}).json()]
    assert all(r["state"] == "unattached" for r in client.get("/api/resources", params={"state": "unattached"}).json())
    costs = [r["monthly_cost"] for r in allr]
    assert costs == sorted(costs, reverse=True)


def test_utilization_endpoints(client):
    s = client.get("/api/utilization/summary").json()
    assert s["resource_count"] > 30 and s["unattached"] == 4 and s["over_utilized"] >= 1
    ts = client.get("/api/utilization/timeseries", params={"days": 7}).json()
    assert len(ts["data"]) == 7 and set(ts["series"]) == {"aws", "azure", "gcp"}
    assert client.get("/api/utilization/timeseries", params={"group_by": "x"}).status_code == 422


def test_optimization_endpoint(client):
    j = client.get("/api/optimization", params={"environment": "development"}).json()
    assert j["summary"]["quick_wins_monthly"] > 0
    assert all(r["environment"] == "development" for r in j["recommendations"])


def test_alert_rule_crud_and_validation(client):
    body = {"name": "Test rule", "rule_type": "daily_cost", "provider": "aws", "threshold": 1, "severity": "critical"}
    created = client.post("/api/alerts/rules", json=body)
    assert created.status_code == 201
    rule = created.json()
    assert rule["status"]["breached"] is True and rule["unit"] == "USD"

    upd = client.put(f"/api/alerts/rules/{rule['id']}", json={**body, "threshold": 100000}).json()
    assert upd["status"]["breached"] is False and upd["threshold"] == 100000

    assert client.post("/api/alerts/rules", json={**body, "rule_type": "nope"}).status_code == 422
    assert client.post("/api/alerts/rules", json={**body, "threshold": -1}).status_code == 422
    assert client.post("/api/alerts/rules", json={**body, "provider": "oracle"}).status_code == 422
    assert client.put("/api/alerts/rules/99999", json=body).status_code == 404

    assert client.delete(f"/api/alerts/rules/{rule['id']}").status_code == 204
    assert client.delete(f"/api/alerts/rules/{rule['id']}").status_code == 404
    assert rule["id"] not in [r["id"] for r in client.get("/api/alerts/rules").json()]


def test_default_rules_present_and_rule_types_listed(client):
    assert len(client.get("/api/alerts/rules").json()) >= 5
    types = {t["type"] for t in client.get("/api/alerts/rule-types").json()}
    assert {"daily_cost", "cpu_high", "potential_savings"} <= types


def test_metrics_endpoint_exposes_prometheus_series(client):
    r = client.get("/metrics")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    text = r.text
    for name in ("devops_cloud_cost_daily_usd", "devops_cloud_cost_projected_month_usd",
                 "devops_alert_rule_value", "devops_alert_rule_threshold", "devops_alert_rule_breached",
                 "devops_resource_cpu_percent", "devops_potential_savings_usd", "devops_idle_resources",
                 "devops_last_collection_success_timestamp_seconds"):
        assert name in text, name
    assert 'provider="aws"' in text and 'severity="critical"' in text


def test_webhook_records_firing_then_resolved(client):
    rule = client.post("/api/alerts/rules", json={"name": "Hook rule", "rule_type": "daily_cost",
                                                  "threshold": 1, "severity": "critical"}).json()
    alert = {"status": "firing", "fingerprint": "fp-test-1", "startsAt": "2026-10-30T06:00:00Z",
             "endsAt": "0001-01-01T00:00:00Z",
             "labels": {"alertname": "DashboardRuleBreached", "rule_id": str(rule["id"]), "severity": "critical"},
             "annotations": {}}
    assert client.post("/api/alerts/webhook", json={"alerts": [alert]}).json() == {"status": "ok", "handled": 1}
    events = client.get("/api/alerts/events").json()
    ev = next(e for e in events if e["rule_id"] == rule["id"])
    assert ev["status"] == "firing" and ev["severity"] == "critical" and ev["value"] > 1
    assert "Hook rule" in ev["summary"]

    resolved = {**alert, "status": "resolved", "endsAt": "2026-10-30T07:00:00Z"}
    client.post("/api/alerts/webhook", json={"alerts": [resolved]})
    same = [e for e in client.get("/api/alerts/events").json() if e["rule_id"] == rule["id"]]
    assert len(same) == 1 and same[0]["status"] == "resolved" and same[0]["ends_at"]
    assert client.get("/api/alerts/events", params={"status": "firing"}).status_code == 200


def test_test_notification_requires_a_channel(client):
    assert client.post("/api/alerts/test").status_code == 409
    assert client.get("/api/alerts/channels").json() == {"slack": False, "teams": False}


def test_provider_status_and_connection_test(client):
    status = client.get("/api/providers/status").json()
    assert [s["provider"] for s in status] == ["aws", "azure", "gcp"]
    assert all(s["mode"] == "mock" and s["last_run_status"] == "success" and s["cost_rows"] > 0 for s in status)
    ok = client.post("/api/providers/aws/test").json()
    assert ok["ok"] is True and ok["mode"] == "mock"
    assert client.post("/api/providers/oracle/test").status_code == 404


def test_manual_collection_trigger(client):
    r = client.post("/api/collect", json={"provider": "gcp", "kinds": ["costs"]})
    assert r.status_code == 202
    assert client.post("/api/collect", json={"kinds": ["bogus"]}).status_code == 422
    assert client.post("/api/collect", json={"provider": "oracle"}).status_code == 422
    assert client.get("/api/collection/runs").json()[0]["provider"] in ("aws", "azure", "gcp")
