# Sprint plan (6 × 20 h) mapped to the implementation

| Sprint | Brief | Delivered in | Hours |
|---|---|---|---|
| **1** Setup and basic cloud integration | Repo and structure; connect to AWS, Azure, GCP; credentials via env; pull sample data and inspect formats | `config.py`, `.env.example`, `collectors/{aws,azure,gcp}.py` (`check_connection`), `docs/CLOUD_SETUP.md`; sample payloads captured as parser tests | Repo + config 3 · connectors 8 · credentials/IAM 3 · sample-data analysis 6 |
| **2** Aggregation and storage | Unified format; schema + DB; scheduled daily jobs; test consistency | `models.py`, `normalize.py`, `services/ingestion.py`, `scheduler.py`, `tests/test_ingestion.py` | Schema 4 · normalisation 4 · ingestion/idempotency 5 · scheduler 3 · tests 4 |
| **3** Real-time dashboard | Frontend; APIs; basic filters; test | `api/*`, `frontend/` Overview + Resources, `FilterBar`, `tests/test_api.py` | API 6 · React shell + filters 5 · Overview 5 · Resources 2 · tests 2 |
| **4** Historical analysis | Trend logic; line/bar charts; advanced filters (date range); validate | `services/analytics.py`, Trends page, custom date range, anomaly + forecast, `tests/test_analytics.py` | Analytics 7 · Trends page 6 · date-range filter 2 · validation tests 5 |
| **5** Alerting | Alertmanager; Slack/Teams; user-defined criteria; document and test | `metrics.py`, `alert_engine.py`, `notifier.py`, `api/alerts.py`, Alerts page, `deploy/prometheus`, `deploy/alertmanager` | Exporter + rules 5 · Alertmanager 3 · notifier 3 · rule editor UI 5 · end-to-end test 4 |
| **6** Final testing, docs, deployment | Extensive testing; user docs; Docker; staging deploy | `Dockerfile`s, `docker-compose.yml`, `docs/`, `tests/`, optimiser + Optimization page (cost-optimisation criterion) | Testing 6 · docs 6 · Docker 3 · optimisation engine 5 |

Hours are a plan-level allocation to the 20 h budget, not a time log.

## Deliverable checklist (from the brief)

| Deliverable | Status |
|---|---|
| Centralised dashboard for AWS, Azure and GCP | Done (mock verified; live collectors untested against real accounts) |
| Real-time and historical visualisation | Done: polling views (15 min inventory, 1 min UI refresh) and 6-month trends |
| Customisable alerting to Slack/Teams | Done and verified end to end with local stand-ins |
| Filters and drill-down by provider, type, environment | Done (+ date range, service breakdown) |
| Documentation (setup, usage, config, troubleshooting) | Done: README + 6 docs |
| Containerised deployment | Written; not executed here (no Docker daemon) |
| Staging deployment | **Not done**: no infrastructure available; Compose file is deployable to any Docker host |
