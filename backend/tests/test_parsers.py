"""Unit tests for the live collectors' response parsers, using sample provider payloads.

The SDK calls themselves need real credentials and are not exercised here; the parsing and
normalisation logic that turns provider responses into unified rows is.
"""
from datetime import date, datetime, timezone

import pytest

from app.collectors.aws import parse_ce_results, parse_cw_datapoints
from app.collectors.azure import parse_azure_query
from app.collectors.gcp import parse_bq_rows


def test_aws_cost_explorer_parsing():
    results = [{
        "TimePeriod": {"Start": "2026-10-28", "End": "2026-10-29"},
        "Groups": [
            {"Keys": ["Amazon Elastic Compute Cloud - Compute", "Environment$prod"],
             "Metrics": {"UnblendedCost": {"Amount": "123.456", "Unit": "USD"}}},
            {"Keys": ["Amazon Simple Storage Service", "Environment$"],
             "Metrics": {"UnblendedCost": {"Amount": "4.5", "Unit": "USD"}}},
            {"Keys": ["AWS Support", "Environment$dev"],
             "Metrics": {"UnblendedCost": {"Amount": "0.0", "Unit": "USD"}}},
        ],
    }]
    rows = parse_ce_results(results, "Environment", account="1234")
    assert len(rows) == 2                                   # zero-cost group dropped
    ec2, s3 = rows
    assert (ec2.date, ec2.provider, ec2.environment, ec2.resource_type) == (
        date(2026, 10, 28), "aws", "production", "compute")
    assert ec2.cost == pytest.approx(123.456) and ec2.account == "1234"
    assert (s3.environment, s3.resource_type) == ("untagged", "storage")


def test_aws_cloudwatch_parsing():
    pts = [{"Timestamp": datetime(2026, 10, 28, tzinfo=timezone.utc), "Average": 12.3456, "Maximum": 40.0}]
    (row,) = parse_cw_datapoints("i-abc", pts)
    assert (row.date, row.resource_id, row.cpu_avg, row.cpu_max) == (date(2026, 10, 28), "i-abc", 12.35, 40.0)


def test_azure_query_parsing():
    columns = ["Cost", "UsageDate", "ServiceName", "TagKey", "TagValue", "Currency"]
    rows = [
        [10.5, 20261029, "Virtual Machines", "Environment", "Dev", "USD"],
        [5.0, 20261029, "Storage Accounts", "", "", "USD"],
        [2.0, 20261029, "Bandwidth", "CostCenter", "42", "USD"],   # a different tag key is ignored
        [0.0, 20261029, "Azure SQL Database", "Environment", "prod", "USD"],
    ]
    out = parse_azure_query(columns, rows, "Environment", account="sub-1")
    assert [(r.service, r.environment, r.resource_type) for r in out] == [
        ("Virtual Machines", "development", "compute"),
        ("Storage Accounts", "untagged", "storage"),
        ("Bandwidth", "untagged", "network"),
    ]
    assert out[0].date == date(2026, 10, 29) and out[0].cost == 10.5


def test_gcp_bigquery_parsing():
    rows = [
        {"usage_date": date(2026, 10, 29), "service": "BigQuery", "project": "p1", "region": "us",
         "currency": "USD", "env": "prod", "net_cost": 42.5},
        {"usage_date": "2026-10-29", "service": "Cloud SQL", "project": "p1", "region": None,
         "currency": "USD", "env": None, "net_cost": 10.0},
        {"usage_date": date(2026, 10, 29), "service": "Cloud Storage", "project": "p1", "region": "us",
         "currency": "USD", "env": "dev", "net_cost": 0},
    ]
    out = parse_bq_rows(rows)
    assert len(out) == 2
    assert (out[0].environment, out[0].resource_type, out[0].account) == ("production", "other", "p1")
    assert (out[1].date, out[1].region, out[1].environment) == (date(2026, 10, 29), "global", "untagged")
