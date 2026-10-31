# Viva preparation

Short, honest answers. Where the project has a weakness, say so first: examiners reward that.

## Design choices

**Why PostgreSQL rather than MongoDB?**
The data is tabular and the queries are aggregations (`SUM … GROUP BY date, provider, environment`).
Unique constraints make ingestion idempotent at the database level. MongoDB's flexibility would only
matter if each provider's raw documents had to be kept as-is; I normalise on the way in instead.

**Why a custom React dashboard instead of Grafana?**
The brief offers either. I needed things Grafana does not do natively: an in-app editor for alert
criteria, optimisation recommendations, and a data-source health page. Prometheus is still exposed, so a
team can add Grafana on top of the same metrics.

**How do users define alerts if Prometheus rules are static YAML?**
The backend stores user rules, evaluates them and exports `devops_alert_rule_breached{rule_id=…}`.
One generic Prometheus rule fires for any series equal to 1. Editing a rule in the UI needs no
Prometheus reload, and Alertmanager still does grouping, de-duplication and repeat intervals.

**Why does Alertmanager call your backend instead of Slack directly?**
Alertmanager's config can't read environment variables, so webhook secrets would end up in a committed file.
Routing via the backend keeps secrets in `.env`, lets me store alert history, enrich messages with the current
value and threshold, and format Teams Adaptive Cards (which Alertmanager can't).

**How is double counting avoided when you re-run collection?**
Ingestion replaces the whole date window for a provider in one transaction, and the table has a unique
key `(date, provider, account, service, environment, region)`. Re-pulling the last 7 days every run also
captures the provider's late revisions.

**How are the three clouds made comparable?**
`normalize.py` maps tags to four environments and service names to five resource types, and every
collector emits the same three row types. Adding a cloud is one new collector class.

## Cloud API knowledge

**Does the GCP Cloud Billing API give you cost data?**
No. It lists billing accounts and the SKU catalogue. Actual spend is in the **billing export to
BigQuery**, which is what the collector queries. The Billing API is used only to verify account access.
(The brief's wording suggests otherwise, so I flagged this in the docs.)

**How is AWS environment derived?**
Cost Explorer is grouped by `SERVICE` and by a tag (`Environment` by default), which must be activated as a
cost-allocation tag. Untagged spend shows as "untagged" rather than being hidden.

**Why are per-resource costs "estimates"?**
Billing APIs report per service, not per instance. I estimate from instance size and list prices to rank
resources and size savings. The cost charts always use billed numbers.

## Algorithms

**How does anomaly detection work and why not mean ± 3σ?**
For each cloud/service/environment, compare a day with the **median** of the previous 14 days, scaled by
the **median absolute deviation**. A spike inflates mean and σ, hiding itself; median/MAD resist that. It
must also be ≥25 % and ≥$10 above baseline, which suppresses noise on small services.

**How is the month-end forecast computed? Weakness?**
`month-to-date + 7-day average × remaining days`. It is simple and explainable, but ignores
seasonality and one-off charges. A spike in the last 7 days inflates it.

**How do you avoid recommending to shrink a bursty server?**
Right-sizing requires average CPU < 20 % **and** peak < 60 %. Idle requires peak < 20 %.

**Why is month-over-month computed per day?**
A partial current month compared on totals shows a false drop. Comparing average daily spend is fair for partial and
28 / 31-day months.

## Evaluation criteria

**Cost optimisation (10 %)** – the optimiser: six recommendation types, savings in dollars,
confidence and effort levels, no double counting, quick wins separated from commitments. Plus budget,
forecast and spike alerts, and anomaly detection. On the demo data it identifies about $3,000 a month of
quick wins out of about $8,200 tracked.

**Implementation (75 %)** – three collectors plus a mock, idempotent ingestion, scheduler, analytics,
optimiser, alert pipeline through Prometheus and Alertmanager to Slack/Teams (verified end to end), React
UI with six pages, Docker Compose, 114 automated tests.

**Documentation (15 %)** – README, architecture, user guide, cloud setup, optimisation method, testing
report, sprint mapping.

## Hard questions

**What did you not test?** Live cloud accounts, the Docker build, real Slack/Teams, and PostgreSQL (tests
use SQLite). All are in `docs/TESTING.md`. Parsers are tested with sample payloads.

**Is the demo data fake?** Yes: deterministic and seeded, with injected anomalies and wasteful resources so
features have something to find. It is labelled *mock* in the UI.

**What is the security weakness?** No authentication on the dashboard or API. In production it belongs
behind SSO/VPN. Credentials come from environment variables or workload identity, and IAM policies are read-only.

**How would it scale to many accounts?** Move collection to workers with a lock, partition
`cost_records` by month, add daily rollup tables, and add an `account` filter (the column already exists).

**What would you do next?** Authentication and per-team views, tag-compliance reporting, Kubernetes
cost allocation, memory metrics via agents, and automated remediation (stop idle dev resources) behind approval.
