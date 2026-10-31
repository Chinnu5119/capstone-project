# User guide

## The filter bar

Cloud, environment, resource type and period apply together on **Overview**, **Trends**,
**Resources** and **Optimization** (the last two show current state, so they ignore the period).
Choose *Custom range* for exact dates. **Reset** clears everything.

## Pages

**Overview** – spend in the period with change versus the previous period of equal length, month to
date, projected month end, latest day and top service. The daily chart can be stacked by cloud,
environment, resource type or service. Below: share by cloud, environment and resource type,
and the **Cost anomalies** table (days far above a service's recent baseline).

**Trends** – monthly cost by cloud, month-over-month change (compared per day, so a partial
month is not shown as a decline), total daily cost, average CPU over time grouped by cloud /
environment / resource type, and cost by service.

**Resources** – inventory with state, current CPU, and estimated monthly cost. Search by name, filter by
state, sort by cost or CPU. CPU colours: red above 85 %, amber below 20 %.

**Optimization** – savings recommendations (see COST_OPTIMIZATION.md). Click a summary tile to filter
the list to that type.

**Alerts** – rules, notification channels and history.

**Data sources** – per-cloud mode, last run, coverage, **Test connection**, **Collect now** and the
collection audit log.

## Alert rules

Create one with **New rule**: choose a condition, a threshold, a severity, and optionally narrow
it to a cloud, environment or resource type.

| Condition | Fires when |
|---|---|
| Daily cost above | The latest day's spend exceeds the threshold (USD) |
| Month-to-date cost above | Spend so far this month exceeds a budget (USD) |
| Projected month-end cost above | MTD + 7-day run rate × remaining days exceeds a budget (USD) |
| Cost spike vs 7-day average | Latest day is more than N % above the previous 7-day average |
| Highest resource CPU above | Any running resource in scope has CPU above N % |
| Idle resources more than | More than N idle running resources |
| Potential savings above | Quick-win savings exceed N (USD/month) |

The comparison is strictly *greater than*. A rule must stay breached for **2 minutes** before it
fires (avoids flapping), then repeats every 4 hours while still breached. When the condition clears
(or you disable or delete the rule) a *resolved* message follows within a few minutes.

## Slack and Teams

**Slack**: create an Incoming Webhook (api.slack.com/apps → Incoming Webhooks) and set
`SLACK_WEBHOOK_URL`.
**Teams**: in the target channel, add a **Workflows** webhook ("Post to a channel when a webhook
request is received") and set `TEAMS_WEBHOOK_URL`. The legacy Office 365 connectors are being
retired by Microsoft; the message uses an Adaptive Card, which the Workflows webhook accepts.

Restart the backend (`docker compose up -d backend`), then press **Send test** on the Alerts page.
Without a webhook, alerts are still recorded in the history ("Recorded only").

## Troubleshooting

| Problem | What to check |
|---|---|
| Header says "Waiting for first collection" | Backend is still doing its first backfill. Wait a few seconds, or **Data sources → Collect all now**. |
| "Cannot reach the API" | `docker compose ps`; backend logs `docker compose logs backend`. |
| Nothing arrives in Slack/Teams | Alerts page shows channels as *not configured*? Set the URL and restart. Check `docker compose logs backend` for "notification failed". Verify Prometheus *Alerts* shows the alert as **Firing** and Alertmanager (:9093) lists it. |
| Alert never fires | Rule must be breached for 2 min. Check Prometheus → Status → Targets: `devops-dashboard` should be UP. |
| Alert history is "Recorded only" | No webhook URL configured, or delivery failed (see logs). |
| Last run shows *partial* or *failed* | Open **Data sources**; the error text names the failing step (costs, resources, utilization) and usually the missing permission. |
| Costs look low for today | Providers publish cost with a delay of up to 24 h; the dashboard shows data through the latest complete day (see header). |
| Environment shows "Untagged" | See tagging in CLOUD_SETUP.md. |
| Numbers differ from the cloud console | Console figures may include tax/support/credits differently; GCP net cost includes credits. Per-resource figures on Resources are estimates. |

## Changing the schedule and thresholds

Environment variables in `.env` (restart the backend): `COST_COLLECTION_INTERVAL_MINUTES`,
`RESOURCE_COLLECTION_INTERVAL_MINUTES`, `IDLE_CPU_THRESHOLD`, `UNDERUSED_CPU_THRESHOLD`,
`OVERUSED_CPU_THRESHOLD`, `OPTIMIZER_WINDOW_DAYS`, `COMMITMENT_DISCOUNT_PCT`, `OFFHOURS_SAVING_PCT`.
