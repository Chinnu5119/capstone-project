"""Slack and Microsoft Teams notifications for alerts received from Alertmanager."""
from __future__ import annotations

import logging

import httpx

from ..config import Settings, get_settings

log = logging.getLogger(__name__)

_COLORS = {"critical": "#D92D20", "warning": "#F79009", "info": "#2E90FA", "resolved": "#12B76A"}
_TEAMS_COLORS = {"critical": "attention", "warning": "warning", "info": "accent", "resolved": "good"}


def _title(alert: dict) -> str:
    state = "RESOLVED" if alert["status"] == "resolved" else alert["severity"].upper()
    return f"[{state}] {alert['rule_name'] or alert['alertname']}"


def _facts(alert: dict) -> list[tuple[str, str]]:
    facts = []
    if alert.get("value") is not None:
        unit = alert.get("unit", "")
        facts.append(("Current", f"{alert['value']:,.2f} {unit}".strip()))
    if alert.get("threshold") is not None:
        facts.append(("Threshold", f"{alert['threshold']:,.2f}"))
    scope = alert.get("scope")
    if scope:
        facts.append(("Scope", scope))
    return facts


def slack_payload(alert: dict, dashboard_url: str) -> dict:
    color = _COLORS["resolved" if alert["status"] == "resolved" else alert["severity"]]
    return {
        "text": _title(alert),
        "attachments": [{
            "color": color, "title": _title(alert), "title_link": f"{dashboard_url}/#/alerts",
            "text": alert.get("summary", ""),
            "fields": [{"title": k, "value": v, "short": True} for k, v in _facts(alert)],
        }],
    }


def teams_payload(alert: dict, dashboard_url: str) -> dict:
    """Adaptive Card in the envelope accepted by Teams 'Workflows' (Power Automate) webhooks."""
    color = _TEAMS_COLORS["resolved" if alert["status"] == "resolved" else alert["severity"]]
    return {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type": "AdaptiveCard", "version": "1.4",
                "body": [
                    {"type": "TextBlock", "text": _title(alert), "weight": "Bolder", "size": "Medium",
                     "color": color, "wrap": True},
                    {"type": "TextBlock", "text": alert.get("summary", ""), "wrap": True},
                    {"type": "FactSet", "facts": [{"title": k, "value": v} for k, v in _facts(alert)]},
                ],
                "actions": [{"type": "Action.OpenUrl", "title": "Open dashboard",
                             "url": f"{dashboard_url}/#/alerts"}],
            },
        }],
    }


def notify(alert: dict, settings: Settings | None = None) -> bool:
    """Send to every configured channel. Returns True if at least one delivery succeeded."""
    s = settings or get_settings()
    targets = []
    if s.slack_webhook_url:
        targets.append(("slack", s.slack_webhook_url, slack_payload(alert, s.dashboard_url)))
    if s.teams_webhook_url:
        targets.append(("teams", s.teams_webhook_url, teams_payload(alert, s.dashboard_url)))
    delivered = False
    for name, url, payload in targets:
        try:
            resp = httpx.post(url, json=payload, timeout=10)
            resp.raise_for_status()
            delivered = True
        except Exception as exc:  # noqa: BLE001 - never let a notification failure break the webhook
            log.warning("%s notification failed: %s", name, exc)
    return delivered


def channels_configured(settings: Settings | None = None) -> dict[str, bool]:
    s = settings or get_settings()
    return {"slack": bool(s.slack_webhook_url), "teams": bool(s.teams_webhook_url)}
