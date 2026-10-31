import pytest

from app import pricing
from app.normalize import categorize_service, normalize_environment, tag_value


def test_aws_monthly_estimate_scales_with_size():
    assert pricing.estimate_monthly("aws", "m5.large") == pytest.approx(70.08, abs=0.01)
    assert pricing.estimate_monthly("aws", "m5.xlarge") == pytest.approx(140.16, abs=0.01)
    assert pricing.estimate_monthly("aws", "db.m5.large") == pytest.approx(70.08 * 1.8, abs=0.05)


@pytest.mark.parametrize("provider,size,expected", [
    ("aws", "m5.xlarge", "m5.large"),
    ("aws", "c5.2xlarge", "c5.xlarge"),
    ("aws", "db.r5.xlarge", "db.r5.large"),
    ("aws", "m5.large", None),          # would drop below 'medium'... large->medium is allowed
    ("aws", "m5.medium", None),
    ("azure", "Standard_D8s_v5", "Standard_D4s_v5"),
    ("azure", "Standard_E16s_v5", "Standard_E8s_v5"),
    ("azure", "Standard_D2s_v5", None),
    ("gcp", "n2-standard-8", "n2-standard-4"),
    ("gcp", "db-n1-standard-8", "db-n1-standard-4"),
    ("gcp", "e2-standard-2", None),
    ("aws", "weird", None),
])
def test_smaller_size(provider, size, expected):
    if (provider, size) == ("aws", "m5.large"):
        expected = "m5.medium"
    assert pricing.smaller_size(provider, size) == expected


def test_smaller_size_is_roughly_half_price():
    for provider, size in (("aws", "m5.2xlarge"), ("azure", "Standard_D8s_v5"), ("gcp", "n2-standard-8")):
        smaller = pricing.smaller_size(provider, size)
        assert pricing.estimate_hourly(provider, smaller) == pytest.approx(
            pricing.estimate_hourly(provider, size) / 2, rel=0.01)


def test_unknown_sizes_return_none():
    assert pricing.estimate_monthly("aws", "zz9.huge") is None
    assert pricing.estimate_monthly("azure", "GP_Gen5_8") is None


def test_volume_price():
    assert pricing.volume_monthly(500, "gp3") == 40.0


@pytest.mark.parametrize("raw,expected", [
    ("prod", "production"), ("PRD", "production"), ("Production", "production"),
    ("dev", "development"), ("development", "development"), ("sandbox", "development"),
    ("stage", "staging"), ("QA", "staging"), ("uat", "staging"),
    ("prod-eu", "production"), ("dev_2", "development"),
    ("", "untagged"), (None, "untagged"), ("misc", "untagged"),
])
def test_normalize_environment(raw, expected):
    assert normalize_environment(raw) == expected


@pytest.mark.parametrize("service,expected", [
    ("Amazon Elastic Compute Cloud - Compute", "compute"), ("EC2 - Other", "compute"),
    ("Amazon Relational Database Service", "database"), ("Amazon Simple Storage Service", "storage"),
    ("Amazon CloudFront", "network"), ("AWS Data Transfer", "network"), ("AWS Lambda", "compute"),
    ("Virtual Machines", "compute"), ("Azure SQL Database", "database"), ("Storage Accounts", "storage"),
    ("Bandwidth", "network"), ("Azure Kubernetes Service", "compute"), ("Azure Cosmos DB", "database"),
    ("Compute Engine", "compute"), ("Cloud SQL", "database"), ("Cloud Storage", "storage"),
    ("BigQuery", "other"), ("Amazon CloudWatch", "other"), (None, "other"),
])
def test_categorize_service(service, expected):
    assert categorize_service(service) == expected


def test_tag_value():
    assert tag_value("Environment$prod", "Environment") == "prod"
    assert tag_value("Environment$", "Environment") == ""
    assert tag_value(None, "Environment") is None
