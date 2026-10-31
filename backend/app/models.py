"""Unified relational schema.

All three clouds are normalised into the same tables, so every query, chart and
alert rule works identically regardless of provider.

Timestamps are stored as naive UTC.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

Money = Numeric(14, 4, asdecimal=False)


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class CostRecord(Base):
    """One day of spend for one (provider, account, service, environment, region)."""

    __tablename__ = "cost_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    account: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    service: Mapped[str] = mapped_column(String(160), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    environment: Mapped[str] = mapped_column(String(32), nullable=False)
    region: Mapped[str] = mapped_column(String(64), nullable=False, default="all")
    cost: Mapped[float] = mapped_column(Money, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")

    __table_args__ = (
        UniqueConstraint(
            "date", "provider", "account", "service", "environment", "region", name="uq_cost_key"
        ),
        Index("ix_cost_filter", "provider", "environment", "resource_type", "date"),
    )


class Resource(Base):
    """Latest inventory snapshot of a cloud resource, with current utilisation."""

    __tablename__ = "resources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(256), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    service: Mapped[str] = mapped_column(String(160), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    size: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    environment: Mapped[str] = mapped_column(String(32), nullable=False)
    region: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="running")
    monthly_cost: Mapped[float] = mapped_column(Money, nullable=False, default=0)
    cpu_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    mem_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_seen: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint("provider", "resource_id", name="uq_resource"),
        Index("ix_resource_filter", "provider", "environment", "resource_type"),
    )


class UtilizationRecord(Base):
    """Daily CPU/memory utilisation for one resource."""

    __tablename__ = "utilization_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(256), nullable=False)
    environment: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    cpu_avg: Mapped[float] = mapped_column(Float, nullable=False)
    cpu_max: Mapped[float] = mapped_column(Float, nullable=False)
    mem_avg: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (
        UniqueConstraint("date", "provider", "resource_id", name="uq_util_key"),
        Index("ix_util_filter", "provider", "environment", "resource_type", "date"),
    )


class AlertRule(Base):
    """A user-defined alert criterion, evaluated by the backend and exported to Prometheus."""

    __tablename__ = "alert_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    rule_type: Mapped[str] = mapped_column(String(48), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(16), nullable=True)
    environment: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resource_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="warning")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )


class AlertEvent(Base):
    """History of alerts received from Alertmanager (firing and resolved)."""

    __tablename__ = "alert_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    rule_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    alertname: Mapped[str] = mapped_column(String(160), nullable=False)
    rule_name: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="warning")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="firing")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    labels: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    starts_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    notified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class CollectionRun(Base):
    """Audit log of every data-collection run."""

    __tablename__ = "collection_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    kinds: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    cost_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    resource_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    util_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
