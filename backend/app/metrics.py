"""Prometheus exporter: cost, utilisation, optimisation and alert-rule state as metrics.

Metrics are computed at scrape time by a custom collector, so a rule that is deleted or
disabled in the dashboard disappears from Prometheus on the next scrape and its alert
resolves automatically (no stale series).
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from datetime import timedelta, timezone

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, generate_latest
from prometheus_client.core import GaugeMetricFamily
from sqlalchemy import func, select

from .config import get_settings
from .db import SessionLocal
from .models import CollectionRun, CostRecord, Resource
from .services import alert_engine, analytics
from .services.filters import Filters, latest_cost_date
from .services.optimizer import recommendations

_CACHE_TTL = 10.0  # seconds; protects the DB from several scrapers hitting at once
_lock = threading.Lock()
_cache: tuple[float, bytes] | None = None


class DashboardCollector:
    def collect(self):
        settings = get_settings()
        with SessionLocal() as db:
            yield from self._cost(db)
            yield from self._resources(db, settings)
            yield from self._rules(db)
            yield from self._collection(db)

    # -- cost -----------------------------------------------------------------
    def _cost(self, db):
        daily = GaugeMetricFamily("devops_cloud_cost_daily_usd",
                                  "Spend on the most recent day with data", labels=["provider", "environment", "resource_type"])
        mtd = GaugeMetricFamily("devops_cloud_cost_month_to_date_usd", "Month-to-date spend", labels=["provider"])
        proj = GaugeMetricFamily("devops_cloud_cost_projected_month_usd", "Projected month-end spend", labels=["provider"])
        anomalies = GaugeMetricFamily("devops_cost_anomalies", "Cost anomalies detected in the last 3 days", labels=["provider"])
        latest = latest_cost_date(db)
        if latest:
            rows = db.execute(select(CostRecord.provider, CostRecord.environment, CostRecord.resource_type,
                                     func.sum(CostRecord.cost)).where(CostRecord.date == latest)
                              .group_by(CostRecord.provider, CostRecord.environment, CostRecord.resource_type))
            for p, e, t, c in rows:
                daily.add_metric([p, e, t], float(c))
            providers = [p for (p,) in db.execute(select(CostRecord.provider).distinct())]
            found = analytics.detect_anomalies(db, Filters(end=latest))
            recent = [a for a in found if a["date"] >= (latest - timedelta(days=2)).isoformat()]
            for p in providers:
                fc = analytics.month_forecast(db, Filters(provider=p), latest)
                mtd.add_metric([p], fc["month_to_date"])
                proj.add_metric([p], fc["projected_month_end"])
                anomalies.add_metric([p], sum(1 for a in recent if a["provider"] == p))
        yield from (daily, mtd, proj, anomalies)

    # -- resources & optimisation -------------------------------------------------
    def _resources(self, db, settings):
        cpu = GaugeMetricFamily("devops_resource_cpu_percent", "Average current CPU of running resources",
                                labels=["provider", "environment", "resource_type"])
        count = GaugeMetricFamily("devops_resources", "Tracked resources by state", labels=["provider", "state"])
        idle = GaugeMetricFamily("devops_idle_resources", "Idle running resources", labels=["provider"])
        savings = GaugeMetricFamily("devops_potential_savings_usd", "Estimated monthly quick-win savings", labels=["provider"])
        buckets: dict[tuple, list[float]] = defaultdict(list)
        states: dict[tuple, int] = defaultdict(int)
        for r in db.scalars(select(Resource)):
            states[(r.provider, r.state)] += 1
            if r.state == "running" and r.cpu_pct is not None:
                buckets[(r.provider, r.environment, r.resource_type)].append(r.cpu_pct)
        for key, vals in buckets.items():
            cpu.add_metric(list(key), sum(vals) / len(vals))
        for (p, st), n in states.items():
            count.add_metric([p, st], n)
        for p in {p for p, _ in states}:
            data = recommendations(db, Filters(provider=p), settings)
            idle.add_metric([p], sum(1 for r in data["recommendations"] if r["type"] == "idle"))
            savings.add_metric([p], data["summary"]["quick_wins_monthly"])
        yield from (cpu, count, idle, savings)

    # -- user-defined alert rules ---------------------------------------------------
    def _rules(self, db):
        labels = ["rule_id", "rule_name", "rule_type", "severity", "provider", "environment", "resource_type"]
        value = GaugeMetricFamily("devops_alert_rule_value", "Current value of a dashboard alert rule", labels=labels)
        threshold = GaugeMetricFamily("devops_alert_rule_threshold", "Threshold of a dashboard alert rule", labels=labels)
        breached = GaugeMetricFamily("devops_alert_rule_breached", "1 if the rule is currently breached", labels=labels)
        for rule, res in alert_engine.evaluate_all(db, only_enabled=True):
            lv = [str(rule.id), rule.name, rule.rule_type, rule.severity,
                  rule.provider or "all", rule.environment or "all", rule.resource_type or "all"]
            value.add_metric(lv, res.value)
            threshold.add_metric(lv, res.threshold)
            breached.add_metric(lv, 1.0 if res.breached else 0.0)
        yield from (value, threshold, breached)

    # -- pipeline health -------------------------------------------------------------
    def _collection(self, db):
        ts = GaugeMetricFamily("devops_last_collection_success_timestamp_seconds",
                               "Unix time of the last successful cost collection", labels=["provider"])
        rows = db.execute(select(CollectionRun.provider, func.max(CollectionRun.finished_at)).where(
            CollectionRun.status.in_(("success", "partial")), CollectionRun.kinds.contains("costs"))
            .group_by(CollectionRun.provider))
        for p, finished in rows:
            if finished:  # stored as naive UTC
                ts.add_metric([p], finished.replace(tzinfo=timezone.utc).timestamp())
        yield ts


registry = CollectorRegistry()
registry.register(DashboardCollector())


def render_metrics() -> tuple[bytes, str]:
    global _cache
    with _lock:
        now = time.monotonic()
        if _cache and now - _cache[0] < _CACHE_TTL:
            return _cache[1], CONTENT_TYPE_LATEST
        body = generate_latest(registry)
        _cache = (now, body)
        return body, CONTENT_TYPE_LATEST
