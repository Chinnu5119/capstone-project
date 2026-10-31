"""Collector interface: every provider (real or mock) emits the same three record types."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date


@dataclass
class CostRow:
    date: date
    provider: str
    service: str
    resource_type: str
    environment: str
    cost: float
    account: str = ""
    region: str = "all"
    currency: str = "USD"


@dataclass
class ResourceRow:
    provider: str
    resource_id: str
    name: str
    service: str
    resource_type: str
    size: str
    environment: str
    region: str
    state: str                       # running | stopped | unattached
    monthly_cost: float
    cpu_pct: float | None = None
    mem_pct: float | None = None


@dataclass
class UtilRow:
    date: date
    provider: str
    resource_id: str
    cpu_avg: float
    cpu_max: float
    mem_avg: float | None = None


class BaseCollector(ABC):
    provider: str
    mode: str

    @abstractmethod
    def check_connection(self) -> tuple[bool, str]:
        """Return (ok, human readable detail)."""

    @abstractmethod
    def fetch_costs(self, start: date, end: date) -> list[CostRow]:
        """Daily cost rows for the inclusive date range."""

    @abstractmethod
    def fetch_resources(self) -> list[ResourceRow]:
        """Current inventory including present CPU utilisation."""

    @abstractmethod
    def fetch_utilization(self, start: date, end: date) -> list[UtilRow]:
        """Daily utilisation history for the inclusive date range."""
