"""Alert rule management, alert history and the Alertmanager webhook receiver."""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import AlertEvent, AlertRule, utcnow
from ..services import notifier
from ..services.alert_engine import RULE_TYPES, SEVERITIES, evaluate_all, evaluate_rule

log = logging.getLogger(__name__)
router = APIRouter(prefix="/alerts", tags=["alerts"])

RuleType = Literal[tuple(RULE_TYPES)]  # type: ignore[valid-type]


class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    rule_type: RuleType
    provider: Literal["aws", "azure", "gcp"] | None = None
    environment: Literal["production", "staging", "development", "untagged"] | None = None
    resource_type: Literal["compute", "database", "storage", "network", "other"] | None = None
    threshold: float = Field(ge=0)
    severity: Literal[tuple(SEVERITIES)] = "warning"  # type: ignore[valid-type]
    enabled: bool = True
    description: str = Field(default="", max_length=1000)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() + "Z" if dt else None


def rule_json(rule: AlertRule, result=None) -> dict:
    out = {
        "id": rule.id, "name": rule.name, "rule_type": rule.rule_type, "provider": rule.provider,
        "environment": rule.environment, "resource_type": rule.resource_type,
        "threshold": rule.threshold, "severity": rule.severity, "enabled": rule.enabled,
        "description": rule.description, "unit": RULE_TYPES[rule.rule_type]["unit"],
        "created_at": _iso(rule.created_at), "updated_at": _iso(rule.updated_at),
    }
    if result is not None:
        out["status"] = {"value": result.value, "breached": result.breached, "detail": result.detail}
    return out


def event_json(e: AlertEvent) -> dict:
    return {
        "id": e.id, "rule_id": e.rule_id, "alertname": e.alertname, "rule_name": e.rule_name,
        "severity": e.severity, "status": e.status, "summary": e.summary, "value": e.value,
        "threshold": e.threshold, "labels": e.labels, "starts_at": _iso(e.starts_at),
        "ends_at": _iso(e.ends_at), "received_at": _iso(e.received_at), "notified": e.notified,
    }


# ------------------------------------------------------------------ rules
@router.get("/rule-types")
def rule_types():
    return [{"type": k, **v} for k, v in RULE_TYPES.items()]


@router.get("/rules")
def list_rules(db: Session = Depends(get_db)):
    return [rule_json(r, res) for r, res in evaluate_all(db)]


@router.post("/rules", status_code=201)
def create_rule(body: RuleIn, db: Session = Depends(get_db)):
    rule = AlertRule(**body.model_dump())
    db.add(rule)
    db.commit()
    return rule_json(rule, evaluate_rule(db, rule))


@router.put("/rules/{rule_id}")
def update_rule(rule_id: int, body: RuleIn, db: Session = Depends(get_db)):
    rule = db.get(AlertRule, rule_id)
    if not rule:
        raise HTTPException(404, "Rule not found")
    for k, v in body.model_dump().items():
        setattr(rule, k, v)
    db.commit()
    return rule_json(rule, evaluate_rule(db, rule))


@router.delete("/rules/{rule_id}", status_code=204)
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    rule = db.get(AlertRule, rule_id)
    if not rule:
        raise HTTPException(404, "Rule not found")
    db.delete(rule)
    db.commit()


# ------------------------------------------------------------------ history
@router.get("/events")
def list_events(status: Literal["firing", "resolved"] | None = None, limit: int = Query(50, ge=1, le=500),
                db: Session = Depends(get_db)):
    stmt = select(AlertEvent).order_by(AlertEvent.starts_at.desc(), AlertEvent.id.desc()).limit(limit)
    if status:
        stmt = stmt.where(AlertEvent.status == status)
    return [event_json(e) for e in db.scalars(stmt)]


@router.get("/channels")
def channels():
    return notifier.channels_configured()


@router.post("/test")
def send_test(db: Session = Depends(get_db)):
    """Send a sample notification to every configured Slack/Teams channel."""
    alert = {"status": "firing", "severity": "info", "alertname": "TestNotification",
             "rule_name": "Test notification", "summary": "This is a test alert from the DevOps Dashboard.",
             "value": 123.45, "threshold": 100.0, "unit": "USD", "scope": "all clouds"}
    configured = notifier.channels_configured()
    if not any(configured.values()):
        raise HTTPException(409, "No notification channel configured: set SLACK_WEBHOOK_URL and/or TEAMS_WEBHOOK_URL")
    return {"delivered": notifier.notify(alert), "channels": configured}


# ------------------------------------------------------------------ Alertmanager webhook
def _parse_ts(value: str | None) -> datetime | None:
    if not value or value.startswith("0001-"):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


@router.post("/webhook")
def alertmanager_webhook(payload: dict = Body(...), authorization: str | None = Header(None),
                         db: Session = Depends(get_db)):
    """Receives Alertmanager's webhook payload, records history and forwards to Slack/Teams."""
    token = get_settings().webhook_token
    if token and authorization != f"Bearer {token}":
        raise HTTPException(401, "Invalid webhook token")

    handled = 0
    for a in payload.get("alerts", []):
        labels, ann = a.get("labels", {}), a.get("annotations", {})
        status = a.get("status", "firing")
        alertname = labels.get("alertname", "Unknown")
        fingerprint = a.get("fingerprint") or hashlib.sha1(
            repr(sorted(labels.items())).encode()).hexdigest()[:16]
        rule = db.get(AlertRule, int(labels["rule_id"])) if str(labels.get("rule_id", "")).isdigit() else None

        value = threshold = None
        unit, scope, summary = "", "", ann.get("summary") or alertname
        if rule:
            res = evaluate_rule(db, rule)
            value, threshold, unit, scope = res.value, rule.threshold, res.unit, res.detail
            summary = f"{rule.name}. {res.detail} (threshold {rule.threshold:g} {res.unit})"
        severity = labels.get("severity") or (rule.severity if rule else "warning")

        event = db.scalar(select(AlertEvent).where(AlertEvent.fingerprint == fingerprint,
                                                   AlertEvent.status == "firing")
                          .order_by(AlertEvent.id.desc()))
        if event is None:
            event = AlertEvent(fingerprint=fingerprint, alertname=alertname, starts_at=_parse_ts(a.get("startsAt")) or utcnow())
            db.add(event)
        event.rule_id = rule.id if rule else None
        event.rule_name = rule.name if rule else labels.get("rule_name", "")
        event.severity = severity if severity in SEVERITIES else "warning"
        event.summary, event.labels = summary, labels
        if value is not None:
            event.value, event.threshold = value, threshold
        event.status = status
        event.ends_at = _parse_ts(a.get("endsAt")) if status == "resolved" else None
        event.received_at = utcnow()
        event.notified = notifier.notify({
            "status": status, "severity": event.severity, "alertname": alertname,
            "rule_name": event.rule_name, "summary": summary, "value": value,
            "threshold": threshold, "unit": unit, "scope": scope,
        })
        handled += 1
    db.commit()
    return {"status": "ok", "handled": handled}
