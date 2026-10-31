# Cost optimisation

The dashboard does not only report spend; it finds specific waste and prices the fix. Each
resource receives at most **one** recommendation (the largest saving), so totals never double count.

## Detection rules

Utilisation uses the last 14 days (`OPTIMIZER_WINDOW_DAYS`), requires at least 3 days of data, and
considers **peak** as well as average so bursty workloads are not mistaken for idle ones.

| Type | Detected when | Action | Saving estimate | Confidence |
|---|---|---|---|---|
| Unattached | Volume attached to nothing | Snapshot, then delete | 100 % of volume cost | High |
| Idle | Avg CPU < 5 % **and** peak < 20 % | Stop / terminate | 100 % | High (non-prod), medium (prod: could be a warm standby) |
| Right-size | Avg CPU < 20 % **and** peak < 60 % | Move one size down | 50 % (one size = half the price within a family) | High (non-prod), medium (prod) |
| Schedule | Dev/staging running 24/7 | Stop nights and weekends | 64 % (12 h × 5 days of 24 × 7 hours is off) | Medium |
| Commitment | Production, avg CPU ≥ 30 %, no other finding | 1-yr Savings Plan / RI / CUD | 30 % (typical 1-yr, no upfront) | Low: needs a purchase decision |
| Over-utilised | Avg CPU > 85 % | Scale up / out | none: a reliability **risk**, shown so savings are not pursued at the expense of stability | High |

Quick wins (the first four) need no purchase and are reported separately from commitments.

## Worked example (bundled demo data)

| | Monthly |
|---|---|
| Tracked run cost (estimated) | $8,172 |
| **Quick wins** (idle $1,504 + schedule $934 + right-size $368 + unattached $210) | **$3,015 (36.9 %)** |
| Commitment discounts | $980 |
| **Total potential** | **$3,996/mo, about $47,900/yr** |

Largest single items: a 16-vCPU Azure dev VM idle at 2 % CPU ($736/mo), an idle GCP dev VM
($284/mo), and two production database commitments ($276 and $192/mo).

These are properties of the synthetic dataset, which deliberately contains each waste pattern.
Real accounts will differ.

## Other cost controls in the product

- **Budget alerts**: month-to-date and projected-month-end rules warn before a budget is crossed,
  not after.
- **Anomaly detection**: median/MAD baseline per cloud/service/environment flags runaway spend
  (e.g. an autoscaling loop or an unpartitioned BigQuery scan) the day it happens.
- **Spike and idle-count alerts** route the above to Slack/Teams.
- **Forecast**: month-end projection = month-to-date + trailing 7-day average × remaining days.

## Limits of the estimates

- Prices are approximate US on-demand list prices, linear within an instance family; actual
  prices vary by region, OS, and existing discounts. They rank and size opportunities; confirm
  with the provider's pricing calculator before acting.
- Right-sizing ignores memory and I/O (memory is not collected from AWS/Azure by default, as
  it needs an agent). Always check before resizing production.
- The commitment figure assumes a 30 % discount; adjust `COMMITMENT_DISCOUNT_PCT` to your
  agreement. It is excluded from "quick wins" for this reason.
- RDS Multi-AZ is estimated at twice single-AZ cost; managed-database sizes that are not
  instance classes (e.g. Azure `GP_Gen5_8`) use explicit monthly cost rather than size pricing.

## Running the dashboard itself cheaply

The stack is five small containers (Postgres, API, nginx, Prometheus, Alertmanager) and fits on
a 2 vCPU / 4 GB instance. Cost Explorer calls are ~$0.01 each; the default schedule is a few
calls a day. Mock mode costs nothing.
