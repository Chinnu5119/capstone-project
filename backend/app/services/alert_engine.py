"""User-defined alert rules.

The backend evaluates each enabled rule against current data and exposes the result to
Prometheus (see metrics.py). A single generic Prometheus rule then fires for any rule whose
value exceeds its threshold, and Alertmanager handles grouping, repeat intervals and routing.
This is what lets users define criteria in the dashboard without editing Prometheus config.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AlertRule, Resource
from .analytics import cost_total, month_forecast
from .filters import Filters, latest_cost_date
from .optimizer import recommendations

SEVERITIES = ("info", "warning", "critical")

RULE_TYPES: dict[str, dict] = {
    "daily_cost": {"label": "Daily cost above", "unit": "USD",
                   "description": "Cost of the most recent day exceeds the threshold.", "default": 500},
    "monthly_cost": {"label": "Month-to-date cost above", "unit": "USD",
                     "description": "Spend so far this month exceeds a budget.", "default": 10000},
    "projected_monthly_cost": {"label": "Projected month-end cost above", "unit": "USD",
                               "description": "Run-rate projection for the month exceeds a budget.", "default": 12000},
    "cost_spike_pct": {"label": "Cost spike vs 7-day average", "unit": "%",
                       "description": "Latest day is this many percent above the previous 7-day average.", "default": 30},
    "cpu_high": {"label": "Highest resource CPU above", "unit": "%",
                 "description": "At least one running resource's current CPU exceeds the threshold.", "default": 90},
    "idle_resource_count": {"label": "Idle resources more than", "unit": "count",
                            "description": "Number of idle running resources exceeds the threshold.", "default": 2},
    "potential_savings": {"label": "Potential monthly savings above", "unit": "USD",
                          "description": "Quick-win optimisation savings exceed the threshold.", "default": 1000},
}


@dataclass
class RuleResult:
    value: float
    threshold: float
    breached: bool
    unit: str
    detail: str


def _scope(rule: AlertRule) -> Filters:
    return Filters(provider=rule.provider, environment=rule.environment, resource_type=rule.resource_type)


def _scope_label(rule: AlertRule) -> str:
    parts = [p for p in (rule.provider and rule.provider.upper(), rule.environment, rule.resource_type) if p]
    return " / ".join(parts) if parts else "all clouds"


def evaluate_rule(db: Session, rule: AlertRule) -> RuleResult:
    meta = RULE_TYPES[rule.rule_type]
    scope = _scope(rule)
    latest = latest_cost_date(db)
    value, detail = 0.0, "No data yet"

    if rule.rule_type == "cpu_high":
        stmt = select(Resource).where(Resource.state == "running", Resource.cpu_pct.is_not(None))
        for col, v in (("provider", rule.provider), ("environment", rule.environment),
                       ("resource_type", rule.resource_type)):
            if v:
                stmt = stmt.where(getattr(Resource, col) == v)
        hot = max(db.scalars(stmt), key=lambda r: r.cpu_pct, default=None)
        if hot:
            value, detail = hot.cpu_pct, f"{hot.name} ({hot.provider.upper()}) at {hot.cpu_pct:.0f}% CPU"
    elif rule.rule_type in ("idle_resource_count", "potential_savings"):
        data = recommendations(db, scope)
        if rule.rule_type == "idle_resource_count":
            idle = [r for r in data["recommendations"] if r["type"] == "idle"]
            value = float(len(idle))
            detail = ", ".join(r["name"] for r in idle[:5]) or "none"
        else:
            value = data["summary"]["quick_wins_monthly"]
            detail = f"{data['summary']['count']} recommendations"
    elif latest is not None:
        if rule.rule_type == "daily_cost":
            value = cost_total(db, replace(scope, start=latest, end=latest))
            detail = f"Spend on {latest.isoformat()}"
        elif rule.rule_type == "monthly_cost":
            value = month_forecast(db, scope, latest)["month_to_date"]
            detail = f"Month to date as of {latest.isoformat()}"
        elif rule.rule_type == "projected_monthly_cost":
            fc = month_forecast(db, scope, latest)
            value = fc["projected_month_end"]
            detail = f"MTD ${fc['month_to_date']:,.0f} + ${fc['daily_run_rate']:,.0f}/day x {fc['days_remaining']} days"
        elif rule.rule_type == "cost_spike_pct":
            today = cost_total(db, replace(scope, start=latest, end=latest))
            base_total = cost_total(db, replace(scope, start=latest - timedelta(days=7), end=latest - timedelta(days=1)))
            base = base_total / 7
            value = (today - base) / base * 100 if base else 0.0
            detail = f"${today:,.0f} vs ${base:,.0f} 7-day average"

    value = round(float(value), 2)
    return RuleResult(value=value, threshold=rule.threshold, breached=value > rule.threshold,
                      unit=meta["unit"], detail=f"{_scope_label(rule)}: {detail}")


def evaluate_all(db: Session, only_enabled: bool = False) -> list[tuple[AlertRule, RuleResult]]:
    stmt = select(AlertRule).order_by(AlertRule.id)
    if only_enabled:
        stmt = stmt.where(AlertRule.enabled.is_(True))
    return [(r, evaluate_rule(db, r)) for r in db.scalars(stmt)]


DEFAULT_RULES = [
    dict(name="Daily cloud spend above $520", rule_type="daily_cost", threshold=520, severity="warning",
         description="Total spend for the latest day across all clouds."),
    dict(name="GCP cost spike above 15% vs 7-day average", rule_type="cost_spike_pct", provider="gcp",
         threshold=15, severity="critical", description="Catches runaway resources early."),
    dict(name="Production CPU above 90%", rule_type="cpu_high", environment="production", threshold=90,
         severity="warning", description="Over-utilised production resources."),
    dict(name="More than 2 idle resources", rule_type="idle_resource_count", threshold=2, severity="info",
         description="Idle compute/database resources that could be stopped."),
    dict(name="Azure projected month-end above $4,300", rule_type="projected_monthly_cost", provider="azure",
         threshold=4300, severity="warning", description="Azure budget guardrail."),
]


def seed_default_rules(db: Session) -> int:
    if db.scalar(select(AlertRule.id).limit(1)) is not None:
        return 0
    for spec in DEFAULT_RULES:
        db.add(AlertRule(**spec))
    db.commit()
    return len(DEFAULT_RULES)
