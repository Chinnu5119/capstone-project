"""Collector factory: picks mock or live implementation per provider from settings."""
from __future__ import annotations

from ..config import Settings
from .base import BaseCollector
from .mock import MockCollector


def get_collector(provider: str, settings: Settings) -> BaseCollector | None:
    mode = settings.mode_for(provider)
    if mode == "disabled":
        return None
    if mode == "mock":
        return MockCollector(provider)
    if provider == "aws":
        from .aws import AwsCollector

        return AwsCollector(settings)
    if provider == "azure":
        from .azure import AzureCollector

        return AzureCollector(settings)
    if provider == "gcp":
        from .gcp import GcpCollector

        return GcpCollector(settings)
    raise ValueError(f"Unknown provider {provider!r}")
