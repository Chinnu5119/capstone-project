import httpx

from app.config import Settings
from app.services import notifier

ALERT = {"status": "firing", "severity": "critical", "alertname": "DashboardRuleBreached",
         "rule_name": "Daily spend", "summary": "Spend too high", "value": 612.5, "threshold": 500.0,
         "unit": "USD", "scope": "all clouds"}


def test_slack_payload_shape():
    p = notifier.slack_payload(ALERT, "http://dash")
    att = p["attachments"][0]
    assert "[CRITICAL] Daily spend" in p["text"] and att["color"] == "#D92D20"
    assert att["title_link"] == "http://dash/#/alerts"
    assert {"title": "Current", "value": "612.50 USD", "short": True} in att["fields"]


def test_resolved_alert_is_marked_resolved():
    p = notifier.slack_payload({**ALERT, "status": "resolved"}, "http://dash")
    assert p["text"].startswith("[RESOLVED]") and p["attachments"][0]["color"] == "#12B76A"


def test_teams_payload_is_adaptive_card():
    p = notifier.teams_payload(ALERT, "http://dash")
    card = p["attachments"][0]
    assert p["type"] == "message" and card["contentType"] == "application/vnd.microsoft.card.adaptive"
    body = card["content"]["body"]
    assert body[0]["text"] == "[CRITICAL] Daily spend" and body[0]["color"] == "attention"
    assert card["content"]["actions"][0]["url"] == "http://dash/#/alerts"


def test_notify_posts_to_each_configured_channel(monkeypatch):
    calls = []

    def fake_post(url, json, timeout):
        calls.append((url, json))
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(notifier.httpx, "post", fake_post)
    s = Settings(slack_webhook_url="https://hooks.slack.test/x", teams_webhook_url="https://teams.test/y")
    assert notifier.notify(ALERT, s) is True
    assert [c[0] for c in calls] == ["https://hooks.slack.test/x", "https://teams.test/y"]


def test_notify_survives_failures_and_reports_them(monkeypatch):
    def boom(url, json, timeout):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(notifier.httpx, "post", boom)
    assert notifier.notify(ALERT, Settings(slack_webhook_url="https://hooks.slack.test/x")) is False
    assert notifier.notify(ALERT, Settings()) is False       # nothing configured
