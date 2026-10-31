# Testing

## Automated: 114 backend tests (`cd backend && pytest`)

| Area | What is verified |
|---|---|
| Pricing / normalisation | Size → price scaling; one-size-down is half price for AWS/Azure/GCP; 14 environment spellings; 19 service-name categorisations |
| Collector parsers | Cost Explorer, Azure Cost Management, BigQuery export and CloudWatch sample payloads → unified rows (zero-cost rows dropped, other tag keys ignored, untagged handled) |
| Ingestion | Running twice produces identical row counts; no duplicate keys; revised figures **replace** old ones; other providers untouched; stale resources removed; one failing step is recorded as *partial* and the rest still run; first run backfills then switches to lookback |
| Analytics | Summary equals raw SQL; every breakdown sums to the total; filters narrow monotonically; time series is dense with consistent totals; forecast arithmetic; month-over-month compares per day; anomalies found without false positives from weekends or tiny services |
| Optimiser | Each rule and boundary (idle vs bursty, prod vs non-prod, too little history); one recommendation per resource; savings never exceed resource cost; totals reconcile |
| Alert rules | All 7 types evaluate; strict `>` threshold; empty database does not crash; scope filters |
| API | Filters combine; invalid values give 422; CRUD with validation; Prometheus series present; webhook records firing then resolved on the same event; manual collection trigger |
| Notifier | Slack and Teams payload structure; delivery to each channel; failures are swallowed and reported |

Tests use deterministic mock data with a fixed clock, so they are repeatable.

## End-to-end check (performed manually during development)

With real Prometheus 2.55.1 and Alertmanager 0.27.0 binaries, the backend, and a stand-in HTTP
endpoint for Slack and Teams:

1. Prometheus scraped `/metrics` and fired `DashboardRuleBreached` for the three breached default rules.
2. Alertmanager grouped them and called `/api/alerts/webhook`.
3. The backend recorded 3 `firing` events and posted 3 Slack and 3 Teams messages with correct
   values (e.g. *GCP cost spike 25.22 % vs 15 % threshold*).
4. Deleting a rule in the API removed its metric; the alert resolved, history showed `resolved`
   with an end time, and a `[RESOLVED]` message was sent.

`promtool check rules` and `amtool check-config` pass on the shipped configuration.
A browser (Playwright/Chromium) loaded all six dashboard pages against the live API with zero
console errors.

## Not tested

- **Live cloud APIs.** No AWS, Azure or GCP account was available. Parsing is covered by sample
  payloads; the SDK calls themselves are not.
- **Docker images / Compose.** The environment had no running Docker daemon, so
  `docker compose up` was not executed. Compose YAML is syntactically valid and the same
  processes were run directly. Expect to fix small issues on first build.
- **Real Slack and Teams.** Payload formats follow the documented schemas but were only
  delivered to a local stand-in.
- **PostgreSQL.** Tests ran on SQLite. The SQL is plain SQLAlchemy Core/ORM, but the Postgres
  path was not executed.
- **Load and scale**, **browser compatibility** beyond Chromium, **accessibility audit**.
- Frontend has no unit tests (build and manual browser check only).

## Manual test checklist

1. `docker compose up --build`; open :8080; Overview shows data through yesterday.
2. Change each filter; numbers and charts change; Reset restores.
3. Trends: all four charts render; month-over-month table shows a "days" badge on the partial month.
4. Alerts → New rule → daily cost above 1 → appears as *Breached*; after about 2 minutes appears in
   Prometheus (:9090/alerts) and in history.
5. Set a webhook, **Send test**, confirm the message.
6. Delete the rule; a resolved message follows within a few minutes.
7. Data sources → Test connection on each cloud; Collect now; history row appears.
