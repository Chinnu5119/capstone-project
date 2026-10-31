# Connecting real cloud accounts

> Status: these collectors follow each provider's documented API and their parsing is
> unit-tested with sample payloads, but they have not been exercised against live accounts.
> Use **Data sources → Test connection** first, then **Collect now**, and check the
> *Collection history* table for errors.

Every provider is independent: `AWS_MODE`, `AZURE_MODE`, `GCP_MODE` accept `mock`, `live` or
`disabled`.

## Tagging (all clouds)

The *environment* filter depends on a tag/label on resources:

| Cloud | Setting | Default key | Values understood |
|---|---|---|---|
| AWS | `AWS_ENVIRONMENT_TAG` | `Environment` | prod/production/prd, stage/staging/stg/qa/uat/test, dev/development/sandbox |
| Azure | `AZURE_ENVIRONMENT_TAG` | `Environment` | same |
| GCP | `GCP_ENVIRONMENT_LABEL` | `environment` | same |

Anything else becomes **untagged**. On AWS the tag must also be activated as a **cost
allocation tag** in Billing → Cost allocation tags (it can take up to 24 h to appear).

## AWS

1. Enable **Cost Explorer** in the Billing console (first use can take 24 h).
2. Create an IAM user or role with this read-only policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "ce:GetCostAndUsage",
      "ec2:DescribeInstances", "ec2:DescribeVolumes",
      "rds:DescribeDBInstances",
      "cloudwatch:GetMetricStatistics",
      "sts:GetCallerIdentity"
    ],
    "Resource": "*"
  }]
}
```

3. `.env`:
```
AWS_MODE=live
AWS_ACCESS_KEY_ID=...        # omit when running on an instance/task role
AWS_SECRET_ACCESS_KEY=...
AWS_REGIONS=us-east-1,eu-west-1     # regions to inventory
```

Note: each Cost Explorer API request costs about $0.01. The default schedule (4 requests a day
plus paging) is negligible.

## Azure

1. Create a service principal: `az ad sp create-for-rbac --name cost-dashboard --skip-assignment`
2. Grant it **Cost Management Reader** and **Reader** on the subscription:
```
az role assignment create --assignee <appId> --role "Cost Management Reader" --scope /subscriptions/<sub>
az role assignment create --assignee <appId> --role "Reader" --scope /subscriptions/<sub>
az role assignment create --assignee <appId> --role "Monitoring Reader" --scope /subscriptions/<sub>
```
3. `.env`:
```
AZURE_MODE=live
AZURE_SUBSCRIPTION_ID=...
AZURE_TENANT_ID=...
AZURE_CLIENT_ID=...
AZURE_CLIENT_SECRET=...
```

The Cost Management API is rate-limited; the collector retries on HTTP 429 with backoff and
requests data in 7-day chunks.

## GCP

Google's **Cloud Billing API does not return spend**; it lists billing accounts and prices.
Spend comes from the **billing export to BigQuery**, so a one-time setup is required:

1. Billing → **Billing export** → enable **Standard usage cost** export to a BigQuery dataset.
   Data starts flowing from the moment you enable it and is **not backfilled**.
2. Create a service account with roles: `BigQuery Job User` (project), `BigQuery Data Viewer`
   (the export dataset), `Compute Viewer`, `Monitoring Viewer`, and `Billing Account Viewer`
   (optional, used by Test connection).
3. Download its JSON key to `./secrets/gcp.json`.
4. `.env`:
```
GCP_MODE=live
GCP_PROJECT_ID=my-project
GCP_BILLING_EXPORT_TABLE=my-project.billing.gcp_billing_export_v1_XXXXXX_XXXXXX_XXXXXX
GCP_BILLING_ACCOUNT_ID=XXXXXX-XXXXXX-XXXXXX
GOOGLE_APPLICATION_CREDENTIALS=/secrets/gcp.json
```

Net cost includes credits (committed-use and sustained-use discounts), matching the console.

## Verifying

```bash
curl -X POST localhost:8000/api/providers/aws/test        # {"ok": true, ...}
curl -X POST localhost:8000/api/collect -H 'content-type: application/json' -d '{"provider":"aws"}'
curl localhost:8000/api/collection/runs | head
```

## Common problems

| Symptom | Cause / fix |
|---|---|
| AWS `AccessDeniedException` on `ce:` | Cost Explorer not enabled, or the policy lacks `ce:GetCostAndUsage`. |
| AWS costs all "untagged" | Tag not activated as a cost allocation tag, or the key differs from `AWS_ENVIRONMENT_TAG`. |
| Azure `429 Too Many Requests` | Throttling; the collector retries, otherwise lower the schedule frequency. |
| Azure empty results | Subscription has no usage in range, or wrong `AZURE_SUBSCRIPTION_ID`. |
| GCP `Not found: Table` | Export not enabled, wrong table name, or no data yet (first rows take hours). |
| GCP costs all "untagged" | Resources are not labelled, or the label key differs from `GCP_ENVIRONMENT_LABEL`. |
