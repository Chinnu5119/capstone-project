"""Ingestion: normalise collector output and write it idempotently.

Re-running a collection for a date window *replaces* that window for that provider
(delete + insert in one transaction), so repeated runs and late-arriving billing revisions
never create duplicates and never leave stale numbers behind.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from ..collectors import get_collector
from ..collectors.base import BaseCollector, CostRow, ResourceRow, UtilRow
from ..config import PROVIDERS, Settings, get_settings
from ..models import CollectionRun, CostRecord, Resource, UtilizationRecord, utcnow

log = logging.getLogger(__name__)

ALL_KINDS = ("resources", "costs", "utilization")


# --------------------------------------------------------------------------- writers
def ingest_costs(db: Session, provider: str, rows: list[CostRow], start: date, end: date) -> int:
    """Replace [start, end] cost data for a provider. Duplicate keys are summed."""
    merged: dict[tuple, dict] = {}
    for r in rows:
        key = (r.date, r.provider, r.account, r.service, r.environment, r.region)
        if key in merged:
            merged[key]["cost"] += r.cost
        else:
            merged[key] = dict(date=r.date, provider=r.provider, account=r.account, service=r.service,
                               resource_type=r.resource_type, environment=r.environment,
                               region=r.region, cost=r.cost, currency=r.currency)
    for rec in merged.values():
        rec["cost"] = round(rec["cost"], 4)
    db.execute(delete(CostRecord).where(
        CostRecord.provider == provider, CostRecord.date >= start, CostRecord.date <= end))
    if merged:
        db.execute(insert(CostRecord), list(merged.values()))
    db.commit()
    return len(merged)


def ingest_resources(db: Session, provider: str, rows: list[ResourceRow]) -> int:
    """Upsert the inventory snapshot; resources no longer reported are removed."""
    existing = {r.resource_id: r for r in db.scalars(select(Resource).where(Resource.provider == provider))}
    seen: set[str] = set()
    now = utcnow()
    for row in rows:
        seen.add(row.resource_id)
        values = dict(name=row.name, service=row.service, resource_type=row.resource_type,
                      size=row.size, environment=row.environment, region=row.region, state=row.state,
                      monthly_cost=row.monthly_cost, cpu_pct=row.cpu_pct, mem_pct=row.mem_pct,
                      last_seen=now)
        res = existing.get(row.resource_id)
        if res is None:
            db.add(Resource(provider=provider, resource_id=row.resource_id, **values))
        else:
            for k, v in values.items():
                setattr(res, k, v)
    for rid, res in existing.items():
        if rid not in seen:
            db.delete(res)
    db.commit()
    return len(rows)


def ingest_utilization(db: Session, provider: str, rows: list[UtilRow], start: date, end: date) -> int:
    meta = {r.resource_id: (r.environment, r.resource_type)
            for r in db.scalars(select(Resource).where(Resource.provider == provider))}
    records = []
    for r in rows:
        if r.resource_id not in meta:
            continue  # utilisation for a resource we do not track (e.g. terminated)
        env, rtype = meta[r.resource_id]
        records.append(dict(date=r.date, provider=provider, resource_id=r.resource_id,
                            environment=env, resource_type=rtype, cpu_avg=r.cpu_avg,
                            cpu_max=r.cpu_max, mem_avg=r.mem_avg))
    db.execute(delete(UtilizationRecord).where(
        UtilizationRecord.provider == provider, UtilizationRecord.date >= start,
        UtilizationRecord.date <= end))
    if records:
        db.execute(insert(UtilizationRecord), records)
    db.commit()
    return len(records)


# --------------------------------------------------------------------------- orchestration
def _has_rows(db: Session, model, provider: str) -> bool:
    return db.scalar(select(func.count()).select_from(model).where(model.provider == provider)) > 0


def collection_windows(db: Session, provider: str, mode: str, settings: Settings, today: date | None = None):
    """First run backfills history; later runs only re-pull a short lookback window."""
    end = (today or date.today()) - timedelta(days=1)
    cost_days = (settings.cost_lookback_days if _has_rows(db, CostRecord, provider)
                 else (settings.mock_history_days if mode == "mock" else settings.cost_history_days))
    util_days = (settings.utilization_lookback_days if _has_rows(db, UtilizationRecord, provider)
                 else settings.utilization_history_days)
    return (end - timedelta(days=cost_days - 1), end), (end - timedelta(days=util_days - 1), end)


def collect_provider(db: Session, provider: str, kinds=ALL_KINDS, settings: Settings | None = None,
                     collector: BaseCollector | None = None) -> CollectionRun | None:
    settings = settings or get_settings()
    collector = collector or get_collector(provider, settings)
    if collector is None:
        return None
    run = CollectionRun(provider=provider, mode=collector.mode, kinds=",".join(kinds))
    db.add(run)
    db.commit()
    errors: list[str] = []
    cost_win, util_win = collection_windows(db, provider, collector.mode, settings)
    # order matters: utilisation rows are keyed by resources written in the first step
    steps = (
        ("resources", lambda: ingest_resources(db, provider, collector.fetch_resources()), "resource_rows"),
        ("costs", lambda: ingest_costs(db, provider, collector.fetch_costs(*cost_win), *cost_win), "cost_rows"),
        ("utilization", lambda: ingest_utilization(
            db, provider, collector.fetch_utilization(*util_win), *util_win), "util_rows"),
    )
    for kind, fn, attr in steps:
        if kind not in kinds:
            continue
        try:
            setattr(run, attr, fn())
        except Exception as exc:  # noqa: BLE001 - one failing step must not stop the others
            db.rollback()
            log.exception("%s %s collection failed", provider, kind)
            errors.append(f"{kind}: {type(exc).__name__}: {exc}")
    run.finished_at = utcnow()
    run.status = "failed" if len(errors) == len(kinds) else ("partial" if errors else "success")
    run.error = "; ".join(errors)[:2000]
    db.add(run)
    db.commit()
    return run


def collect_all(db: Session, kinds=ALL_KINDS, settings: Settings | None = None,
                providers: list[str] | None = None) -> list[CollectionRun]:
    settings = settings or get_settings()
    runs = []
    for provider in providers or list(PROVIDERS):
        run = collect_provider(db, provider, kinds, settings)
        if run:
            runs.append(run)
    return runs


def provider_status(db: Session, settings: Settings | None = None) -> list[dict]:
    """Mode, last run and cost-data coverage for each provider (used by the Data Sources page)."""
    settings = settings or get_settings()
    out = []
    for provider in PROVIDERS:
        mode = settings.mode_for(provider)
        last = db.scalar(select(CollectionRun).where(CollectionRun.provider == provider)
                         .order_by(CollectionRun.id.desc()).limit(1))
        last_ok = db.scalar(select(func.max(CollectionRun.finished_at)).where(
            CollectionRun.provider == provider, CollectionRun.status.in_(("success", "partial"))))
        lo, hi, n = db.execute(select(func.min(CostRecord.date), func.max(CostRecord.date),
                                      func.count()).where(CostRecord.provider == provider)).one()
        out.append({
            "provider": provider, "mode": mode,
            "last_run_status": last.status if last else None,
            "last_run_error": last.error if last else "",
            "last_success_at": last_ok.isoformat() + "Z" if last_ok else None,
            "cost_rows": n, "first_date": lo.isoformat() if lo else None,
            "last_date": hi.isoformat() if hi else None,
        })
    return out


def group_sum(rows, key):  # small helper shared by tests
    acc = defaultdict(float)
    for r in rows:
        acc[key(r)] += r.cost
    return acc
