"""Approximate on-demand pricing used to *estimate* per-resource monthly cost.

Billing APIs report cost per service, not per instance. To rank individual resources and
size optimisation savings we estimate monthly cost from instance size. Numbers are
approximate US on-demand Linux list prices and are intentionally simple: within a family,
price scales linearly with size, which is also how clouds price (one size down ~ half).
These are estimates, never used for the billed-cost charts.
"""
from __future__ import annotations

import re

HOURS_PER_MONTH = 730

# ---- AWS --------------------------------------------------------------------
_AWS_LARGE_HOURLY = {
    "t3": 0.0832, "t3a": 0.0752, "m5": 0.096, "m6i": 0.096, "m7g": 0.0816,
    "c5": 0.085, "c6i": 0.085, "r5": 0.126, "r6i": 0.126,
}
_AWS_SIZES = ["nano", "micro", "small", "medium", "large", "xlarge", "2xlarge", "4xlarge",
              "8xlarge", "12xlarge", "16xlarge", "24xlarge"]
_AWS_MULT = {"nano": 0.0625, "micro": 0.125, "small": 0.25, "medium": 0.5, "large": 1,
             "xlarge": 2, "2xlarge": 4, "4xlarge": 8, "8xlarge": 16, "12xlarge": 24,
             "16xlarge": 32, "24xlarge": 48}
_RDS_PREMIUM = 1.8  # RDS instance classes cost ~1.8x the matching EC2 type

# ---- Azure ------------------------------------------------------------------
_AZURE_PER_VCPU = {"D": 0.048, "E": 0.063, "F": 0.0423, "B": 0.0208}
_AZURE_RE = re.compile(r"^Standard_([A-Za-z]+)(\d+)([a-z]*)(?:_(v\d+))?$")

# ---- GCP --------------------------------------------------------------------
_GCP_PER_VCPU = {
    "e2-standard": 0.0335, "n2-standard": 0.0486, "n2-highmem": 0.0655,
    "n1-standard": 0.0475, "c2-standard": 0.0522,
}
_GCP_RE = re.compile(r"^(db-)?([a-z0-9]+-[a-z]+)-(\d+)$")

# ---- Block storage ($/GB-month) ------------------------------------------------
VOLUME_PRICE_PER_GB = {
    "gp3": 0.08, "gp2": 0.10, "io1": 0.125, "st1": 0.045, "sc1": 0.015,           # AWS EBS
    "Premium_LRS": 0.154, "StandardSSD_LRS": 0.075, "Standard_LRS": 0.04,         # Azure disks
    "pd-ssd": 0.17, "pd-balanced": 0.10, "pd-standard": 0.04,                     # GCP PD
}


def volume_monthly(size_gb: float, volume_type: str) -> float:
    return round(size_gb * VOLUME_PRICE_PER_GB.get(volume_type, 0.10), 2)


def estimate_hourly(provider: str, size: str) -> float | None:
    """Estimated on-demand $/hour, or None if the size is not recognised."""
    try:
        if provider == "aws":
            s = size.lower()
            factor = 1.0
            if s.startswith("db."):
                s, factor = s[3:], _RDS_PREMIUM
            family, _, sz = s.partition(".")
            if family in _AWS_LARGE_HOURLY and sz in _AWS_MULT:
                return _AWS_LARGE_HOURLY[family] * _AWS_MULT[sz] * factor
        elif provider == "azure":
            m = _AZURE_RE.match(size)
            if m and m.group(1).upper() in _AZURE_PER_VCPU:
                return _AZURE_PER_VCPU[m.group(1).upper()] * int(m.group(2))
        elif provider == "gcp":
            m = _GCP_RE.match(size)
            if m and m.group(2) in _GCP_PER_VCPU:
                return _GCP_PER_VCPU[m.group(2)] * int(m.group(3))
    except (ValueError, KeyError):
        return None
    return None


def estimate_monthly(provider: str, size: str) -> float | None:
    hourly = estimate_hourly(provider, size)
    return None if hourly is None else round(hourly * HOURS_PER_MONTH, 2)


def smaller_size(provider: str, size: str) -> str | None:
    """The next size down in the same family (about half the price), or None if not sensible."""
    if provider == "aws":
        prefix = "db." if size.lower().startswith("db.") else ""
        body = size[len(prefix):]
        family, _, sz = body.partition(".")
        if sz in _AWS_SIZES:
            idx = _AWS_SIZES.index(sz)
            if idx >= _AWS_SIZES.index("large"):      # never recommend below 'medium'
                return f"{prefix}{family}.{_AWS_SIZES[idx - 1]}"
        return None
    if provider == "azure":
        m = _AZURE_RE.match(size)
        if m and int(m.group(2)) >= 4:
            tail = f"_{m.group(4)}" if m.group(4) else ""
            return f"Standard_{m.group(1)}{int(m.group(2)) // 2}{m.group(3)}{tail}"
        return None
    if provider == "gcp":
        m = _GCP_RE.match(size)
        if m and int(m.group(3)) >= 4:
            return f"{m.group(1) or ''}{m.group(2)}-{int(m.group(3)) // 2}"
        return None
    return None
