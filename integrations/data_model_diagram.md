# CX Intelligence Stack — Data Architecture

**Version:** 1.0  
**Scope:** Fleet SaaS DACH — Post-merger customer portfolio  
**Systems:** Planhat · Salesforce · Zendesk · Product DB · BigQuery · dbt · Looker Studio

---

## Full Stack Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           SOURCE SYSTEMS                                    │
├──────────────┬──────────────┬──────────────┬──────────────────────────────-─┤
│   PLANHAT    │  SALESFORCE  │   ZENDESK    │       PRODUCT DATABASE          │
│              │              │              │                                 │
│ • Companies  │ • Account    │ • Tickets    │ • GPS ping events               │
│ • Metrics    │ • Opportunity│ • CSAT       │ • Logbook entries               │
│ • NPS        │ • Contract   │ • SLA data   │ • Admin login events            │
│ • Tasks      │ • Task       │              │ • Mobile app sessions           │
│ • Licences   │              │              │ • Report generation events      │
└──────┬───────┴──────┬───────┴──────┬───────┴────────────────┬────────────────┘
       │              │              │                         │
       │ REST API     │ Bulk API 2.0 │ REST API               │ CDC / Export
       │ (nightly)    │ + CDC        │ (hourly)               │ (daily)
       │              │              │                         │
       ▼              ▼              ▼                         ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        BIGQUERY RAW LAYER                                   │
│                                                                             │
│  raw_planhat.companies          raw_salesforce.accounts                     │
│  raw_planhat.datapoints         raw_salesforce.opportunities                │
│  raw_planhat.nps_responses      raw_salesforce.contracts                    │
│  raw_zendesk.tickets            raw_product.gps_events                      │
│  raw_zendesk.csat_scores        raw_product.login_events                    │
│                                 raw_product.logbook_entries                 │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                  dbt transform
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        BIGQUERY STAGING LAYER (dbt)                         │
│                                                                             │
│  stg_planhat__companies         stg_salesforce__accounts                    │
│  stg_planhat__datapoints        stg_salesforce__opportunities               │
│  stg_planhat__nps               stg_salesforce__contracts                   │
│  stg_zendesk__tickets           stg_product__usage_signals                  │
│                                                                             │
│  → Deduplication, type casting, field renaming, null handling               │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                  dbt transform
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      BIGQUERY INTERMEDIATE LAYER (dbt)                      │
│                                                                             │
│  int_customer_master            → Joined Account + Company + Contract       │
│  int_usage_signals              → Aggregated product signals per customer   │
│  int_support_signals            → Ticket + CSAT rollup per customer         │
│  int_relationship_signals       → NPS + QBR completion per customer         │
│  int_mrr_movements              → Monthly MRR waterfall (churn/expand)      │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                  dbt transform
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         BIGQUERY MART LAYER (dbt)                           │
│                                                                             │
│  mart_customer_health_scores    ← health_scoring.py logic as dbt model     │
│  mart_nrr_grr_monthly           ← retention_analysis.py NRR/GRR logic      │
│  mart_renewal_pipeline          ← 90-day ARR-weighted renewal view         │
│  mart_cs_intervention_list      ← Prioritised CSM action queue             │
│  mart_segment_health_summary    ← Executive segment roll-up                │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                    ┌──────────────────┼──────────────────┐
                    │                  │                   │
                    ▼                  ▼                   ▼
          ┌──────────────┐   ┌──────────────────┐  ┌────────────────┐
          │ LOOKER STUDIO│   │     PLANHAT       │  │  SALESFORCE    │
          │              │   │                  │  │                │
          │ Exec dashboard│   │ Health score sync│  │ Health tier    │
          │ NRR/GRR trend│   │ Lifecycle signals│  │ written to     │
          │ Renewal view │   │ CSM task triggers│  │ Account object │
          │ CS team ops  │   │                  │  │                │
          └──────────────┘   └──────────────────┘  └────────────────┘
```

---

## dbt Model Dependency Graph

```
raw sources
    │
    ├── stg_planhat__companies
    │       └── int_customer_master ──────────────────────┐
    ├── stg_salesforce__accounts ──────────────────────────┤
    ├── stg_salesforce__contracts ─────────────────────────┤
    │                                                       │
    ├── stg_product__usage_signals                          │
    │       └── int_usage_signals ─────────────────────────┤
    │                                                       ▼
    ├── stg_zendesk__tickets                     mart_customer_health_scores
    │       └── int_support_signals ─────────────────────  │
    │                                                       │
    ├── stg_planhat__nps                                    │
    │       └── int_relationship_signals ─────────────────  │
    │                                                       │
    └── stg_salesforce__opportunities                       │
            └── mart_renewal_pipeline ◄────────────────────┘
                    └── mart_cs_intervention_list

    stg_planhat__datapoints
            └── int_mrr_movements
                    └── mart_nrr_grr_monthly
```

---

## Refresh Schedule

| Pipeline | Trigger | Frequency | Destination |
|---|---|---|---|
| Planhat companies → BQ | Cloud Scheduler | Nightly 02:00 CET | `raw_planhat.companies` |
| Planhat datapoints → BQ | Cloud Scheduler | Nightly 02:15 CET | `raw_planhat.datapoints` |
| Planhat NPS → BQ | Cloud Scheduler | Nightly 02:30 CET | `raw_planhat.nps_responses` |
| Salesforce → BQ | Fivetran / CDC | Nightly 01:00 CET | `raw_salesforce.*` |
| Zendesk → BQ | Fivetran | Hourly | `raw_zendesk.*` |
| Product DB → BQ | Custom export | Daily 00:30 CET | `raw_product.*` |
| dbt run (staging) | dbt Cloud | Nightly 03:00 CET | `staging.*` |
| dbt run (marts) | dbt Cloud | Nightly 04:00 CET | `mart.*` |
| Health score → Planhat | dbt + webhook | Nightly 05:00 CET | Planhat API push |
| Health tier → Salesforce | Planhat webhook | Real-time | SFDC Account |

---

## Key Design Decisions

**Why BigQuery as the join layer, not Planhat?**
Planhat's analytics are customer-centric by design — they don't support arbitrary SQL
joins across objects. NRR/GRR calculation from the MRR waterfall requires a pivot on
12 months of data per customer, which is a BigQuery operation, not a Planhat report.

**Why dbt for transformation, not raw SQL?**
Version-controlled models, test coverage (schema tests + custom tests), and lineage
documentation. The mart layer models map 1:1 to the Python logic in this repo —
the Python files are the prototype, dbt models are the production equivalent.

**Why not write health scores directly from BigQuery to Planhat?**
We do — nightly. But Planhat is the operational surface where CSMs work. The
Planhat health score is the version CSMs see in their daily workflow. BigQuery
is the analytical version for reporting and model iteration. They should agree;
if they diverge, BigQuery is the source of truth for the discrepancy investigation.

**Why real-time webhook from Planhat → Salesforce, but nightly for the reverse?**
Health tier changes have operational urgency (CSM needs to know today, not tomorrow).
Contract/ARR data changes are low-frequency and don't require real-time propagation.
Optimise for operational impact, not architectural symmetry.

---

## Environment Variables Required

```bash
# Planhat
PLANHAT_API_TOKEN=your_planhat_api_token

# Google Cloud
GCP_PROJECT_ID=your-gcp-project-id
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json

# Salesforce (if using direct SFDC → BQ pipeline vs Fivetran)
SF_USERNAME=your@email.com
SF_PASSWORD=yourpassword
SF_SECURITY_TOKEN=yoursecuritytoken
SF_DOMAIN=login  # or 'test' for sandbox
```

Store secrets in Google Secret Manager in production. Never commit to version control.
