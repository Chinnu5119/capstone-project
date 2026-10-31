"""Normalisation of provider-specific vocabulary into one shared taxonomy."""
from __future__ import annotations

RESOURCE_TYPES = ("compute", "database", "storage", "network", "other")
ENVIRONMENTS = ("production", "staging", "development", "untagged")

_ENV_ALIASES = {
    "production": {"prod", "production", "prd", "live"},
    "staging": {"stage", "staging", "stg", "test", "testing", "qa", "uat"},
    "development": {"dev", "development", "develop", "sandbox", "sbx"},
}

# Order matters: first matching group wins.
_TYPE_KEYWORDS = (
    ("database", (
        "relational database", "rds", "sql", "database", "dynamodb", "cosmos", "redshift",
        "elasticache", "bigtable", "spanner", "firestore", "documentdb", "memorystore", "redis",
    )),
    ("storage", (
        "s3", "storage", "ebs", "efs", "glacier", "disk", "blob", "backup", "filestore",
        "snapshot", "archive",
    )),
    ("network", (
        "cloudfront", "data transfer", "bandwidth", "vpc", "network", "load balanc", "route 53",
        "cdn", "nat gateway", "vpn", "dns", "direct connect", "api gateway",
    )),
    ("compute", (
        "ec2", "elastic compute", "lambda", "eks", "ecs", "fargate", "virtual machine", "compute",
        "kubernetes", "container", "app service", "functions", "gke", "batch", "lightsail",
        "cloud run",
    )),
)


def normalize_environment(value: str | None) -> str:
    """Map free-form tag/label values ('prod', 'PRD', 'Dev-2') onto the shared environment set."""
    if not value:
        return "untagged"
    v = value.strip().lower()
    for env, aliases in _ENV_ALIASES.items():
        if v in aliases:
            return env
    # tolerate suffixes such as "prod-eu" or "dev_2"
    head = v.replace("_", "-").split("-")[0]
    for env, aliases in _ENV_ALIASES.items():
        if head in aliases:
            return env
    return "untagged"


def categorize_service(service_name: str | None) -> str:
    """Map a provider service name ('Amazon Relational Database Service') to a resource type."""
    s = (service_name or "").lower()
    for rtype, words in _TYPE_KEYWORDS:
        if any(w in s for w in words):
            return rtype
    return "other"


def tag_value(raw: str | None, tag_key: str) -> str | None:
    """Cost Explorer returns tag groups as 'Environment$prod'; strip the key prefix."""
    if raw is None:
        return None
    prefix = f"{tag_key}$"
    return raw[len(prefix):] if raw.startswith(prefix) else raw
