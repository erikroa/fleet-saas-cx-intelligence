# Planhat API Schema - CX Intelligence Integration Reference

**Purpose:** Field-level mapping between Planhat's REST API objects and the four-dimension
health model used in this project. Use this as the canonical reference when configuring
Planhat health dimensions, writing pipeline extraction queries, or debugging signal mismatches.

**Base URL:** `https://api.planhat.com`  
**Auth:** Bearer token via `Authorization: Bearer {PLANHAT_API_TOKEN}` header  
**Rate limits:** 200 requests/minute (standard tier). Paginate using `offset` + `limit` params.

---

## Core API Objects

### 1. Companies (`/companies`)

The customer master record in Planhat. Maps to our `customers` table.

| Planhat Field | Type | Our Field | Notes |
|---|---|---|---|
| `_id` | string | `planhat_id` | Planhat internal ID |
| `externalId` | string | `customer_id` | Set to Salesforce Account ID for bi-directional sync |
| `name` | string | `company_name` | |
| `phase` | string | `lifecycle_stage` | Planhat lifecycle: `onboarding`, `adoption`, `expansion`, `renewal`, `churned` |
| `mr` | float | `mrr` | Monthly recurring revenue in account currency |
| `mrr` | float | `mrr` | Alias - use `mr` as source of truth in API responses |
| `arr` | float | `arr` | Annual recurring revenue |
| `renewalDate` | date | `renewal_date` | ISO 8601. Pull from Salesforce Contract if Planhat is not master |
| `contractSignedDate` | date | `contract_start_date` | |
| `custom.vehicle_count` | int | `vehicle_count` | Custom field - must be created in Planhat UI first |
| `custom.legacy_system` | string | `legacy_system` | Values: `Vimcar`, `Avrios`, `Optimum Automotive`, `New Logo` |
| `custom.country` | string | `country` | ISO 3166-1 alpha-2: `DE`, `AT`, `CH` |
| `custom.segment` | string | `segment` | Values: `SMB`, `Mid-Market`, `Enterprise` |
| `nrr` | float | - | Planhat-calculated NRR - validate against our BigQuery calculation |
| `health` | int | `health_score` | Planhat composite score 0-100. We override with our custom model. |
| `csmId` | string | `csm_owner_id` | References Planhat User object |
| `tags` | array | - | Use for cohort segmentation (e.g. `["post-merger", "migration-q1-2024"]`) |

**Pagination example:**
```
GET /companies?limit=100&offset=0&select=_id,externalId,name,phase,mr,arr,renewalDate,health
```

---

### 2. Metrics (`/metrics`, `/datapoints`)

Time-series signals. This is where product usage lands - GPS adoption, logbook completion,
login frequency. Each metric is defined once in Planhat and populated via API push or 
native integration.

**Metric definitions (configured in Planhat UI):**

| Metric Name | `externalId` | Aggregation | Source System | Maps To |
|---|---|---|---|---|
| GPS Active Vehicle Rate | `gps_adoption_pct` | Last value | Product DB → BigQuery | `adoption_score` (50% weight) |
| Logbook Completion Rate | `logbook_completion_pct` | Last value | Product DB → BigQuery | `adoption_score` (25% weight) |
| Reports Generated (30d) | `reports_generated_30d` | Sum | Product DB → BigQuery | `adoption_score` (25% weight) |
| Days Since Last Admin Login | `days_since_last_login` | Last value | Product DB → BigQuery | `engagement_score` (40% weight) |
| Mobile DAU/MAU | `mobile_dau_mau` | Last value | Product DB → BigQuery | `engagement_score` (35% weight) |
| Onboarding Score | `onboarding_completion_score` | Last value | Internal CS ops | `engagement_score` (25% weight) |

**Push datapoint to Planhat:**
```
POST /datapoints
{
  "companyExternalId": "CUST-0042",
  "dimensionId": "gps_adoption_pct",
  "value": 87.3,
  "date": "2024-12-31"
}
```

**Pull all datapoints for a company:**
```
GET /datapoints?companyId={planhat_id}&from=2024-01-01&to=2024-12-31
```

---

### 3. NPS (`/nps`)

Survey responses. We use these in the `relationship_score` dimension.

| Planhat Field | Type | Our Field | Notes |
|---|---|---|---|
| `_id` | string | — | |
| `companyId` | string | — | References Company `_id` |
| `score` | int | `nps_score` | 0–10 |
| `feedback` | string | — | Qualitative — not used in scoring model |
| `created` | date | — | Survey date |
| `campaignId` | string | — | Use to filter by survey wave |

**Key decision:** Non-responses are scored as 50 (neutral) in our model, not 0.
This prevents penalising accounts where CS simply hasn't surveyed yet.

---

### 4. Tasks (`/tasks`)

CSM activity log. Used to validate QBR completion signal.

| Planhat Field | Type | Our Field | Notes |
|---|---|---|---|
| `_id` | string | - | |
| `companyId` | string | - | |
| `type` | string | - | Filter on `"type": "meeting"` for QBRs |
| `mainType` | string | - | Use `"QBR"` as the standard value |
| `status` | string | - | `"done"` = completed |
| `dueDate` | date | - | |
| `completedAt` | date | - | Null if not completed |

**QBR completion logic:**
```python
qbr_done = tasks.filter(
    type="QBR",
    status="done",
    completedAt__gte=quarter_start,
    completedAt__lte=quarter_end
).exists()
```

---

### 5. Licences (`/licences`)

ARR/MRR line items at the product level. Needed for expansion MRR tracking.

| Planhat Field | Type | Our Field | Notes |
|---|---|---|---|
| `_id` | string | - | |
| `companyId` | string | - | |
| `product` | string | `product_name` | e.g. `"GPS Tracking"`, `"Digital Logbook"` |
| `value` | float | `mrr` | Monthly value of this licence |
| `fromDate` | date | `licence_start` | |
| `toDate` | date | `licence_end` | |
| `renewalDate` | date | `renewal_date` | Can differ per product line |
| `status` | string | - | `"active"`, `"churned"` |

**Expansion MRR detection:**
Compare current period `SUM(value)` per company to prior period.
Positive delta = expansion. Negative delta = contraction.

---

## Health Dimension Configuration

Planhat supports native health dimensions that aggregate into a composite score.
Our model maps to Planhat's four standard dimension types:

| Planhat Dimension | Our Dimension | Weight | Primary Signals |
|---|---|---|---|
| `adoption` | Adoption | 35% | `gps_adoption_pct`, `logbook_completion_pct`, `reports_generated_30d` |
| `engagement` | Engagement | 30% | `days_since_last_login`, `mobile_dau_mau`, `onboarding_completion_score` |
| `support` | Support Health | 20% | Open tickets (Zendesk), CSAT, resolution time |
| `nps` / custom | Relationship | 15% | NPS score, QBR completion flag |

**Implementation note:** Planhat allows custom scoring formulas per dimension.
Use the formula editor to replicate the weighted scoring logic in `models/health_scoring.py`.
The Python model is the source of truth for logic; Planhat is the operational surface.

---

## Known API Gotchas

**`mr` vs `mrr`:** Both fields exist in the Company object. `mr` is the editable field;
`mrr` is sometimes calculated. Use `mr` as source of truth when writing pipelines.

**Custom fields:** Any field prefixed `custom.` must be pre-created in Planhat Settings
before it can be written via API. Check field existence before pipeline runs.

**Pagination:** The API does not return a `total_count` by default. Paginate until you
receive an empty array, not until `offset >= total`.

**Timestamps:** Planhat returns timestamps in milliseconds since epoch in some endpoints
and ISO 8601 in others. Normalise to ISO on ingest.

**Webhook vs poll:** Planhat supports outbound webhooks on Company health changes.
Prefer webhooks over polling for triggering real-time CSM alerts in Salesforce.
Use polling for nightly full-refresh loads to BigQuery.
