"""Application settings, loaded from environment variables (or a .env file)."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

PROVIDERS = ("aws", "azure", "gcp")
MODES = ("mock", "live", "disabled")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- core -------------------------------------------------------------
    database_url: str = "sqlite:///./devops_dashboard.db"
    cors_origins: str = "*"
    dashboard_url: str = "http://localhost:8080"

    # --- provider modes: mock | live | disabled ----------------------------
    aws_mode: str = "mock"
    azure_mode: str = "mock"
    gcp_mode: str = "mock"

    # --- collection schedule ----------------------------------------------
    scheduler_enabled: bool = True
    seed_on_startup: bool = True
    cost_collection_interval_minutes: int = 360
    resource_collection_interval_minutes: int = 15
    cost_lookback_days: int = 7            # re-pull recent days: providers revise late
    cost_history_days: int = 90            # first-run backfill for live providers
    mock_history_days: int = 120           # first-run backfill for mock providers
    utilization_history_days: int = 30
    utilization_lookback_days: int = 3

    # --- optimisation thresholds ------------------------------------------
    idle_cpu_threshold: float = 5.0
    underused_cpu_threshold: float = 20.0
    overused_cpu_threshold: float = 85.0
    optimizer_window_days: int = 14
    commitment_discount_pct: float = 30.0   # typical 1-yr savings plan / RI estimate
    offhours_saving_pct: float = 64.0       # stop 12h/day on weekdays => ~64% off

    # --- notifications -----------------------------------------------------
    slack_webhook_url: str = ""
    teams_webhook_url: str = ""
    webhook_token: str = ""                 # optional bearer token for /api/alerts/webhook

    # --- AWS ---------------------------------------------------------------
    aws_regions: str = "us-east-1"          # comma separated, for EC2/RDS/EBS inventory
    aws_environment_tag: str = "Environment"

    # --- Azure -------------------------------------------------------------
    azure_subscription_id: str = ""
    azure_environment_tag: str = "Environment"

    # --- GCP ---------------------------------------------------------------
    gcp_project_id: str = ""
    gcp_billing_account_id: str = ""
    gcp_billing_export_table: str = ""      # project.dataset.gcp_billing_export_v1_XXXX
    gcp_environment_label: str = "environment"

    def mode_for(self, provider: str) -> str:
        mode = getattr(self, f"{provider}_mode").strip().lower()
        if mode not in MODES:
            raise ValueError(f"{provider.upper()}_MODE must be one of {MODES}, got {mode!r}")
        return mode

    def provider_modes(self) -> dict[str, str]:
        return {p: self.mode_for(p) for p in PROVIDERS}

    def enabled_providers(self) -> list[str]:
        return [p for p, m in self.provider_modes().items() if m != "disabled"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
