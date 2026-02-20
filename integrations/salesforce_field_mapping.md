# Salesforce Field Mapping - CX Intelligence Integration Reference

**Purpose:** Defines which Salesforce objects feed the CX intelligence stack, which system
owns each field, and how SFDC data joins to Planhat and BigQuery. This is the
system-of-record design document, the reference for resolving conflicts when the
same field exists in multiple systems.

**Integration pattern:** Salesforce → BigQuery (via scheduled extract or Change Data Capture)
Planhat reads contract/ARR fields from BigQuery, not directly from SFDC.
Salesforce reads health tier and churn risk flag from Planhat via webhook → Flow.

---

## System-of-Record Ownership

| Field Category | System of Record | Sync Direction | Frequency |
|---|---|---|---|
| Contract ARR / MRR | Salesforce | SFDC → BigQuery → Planhat | Nightly |
| Renewal date | Salesforce | SFDC → BigQuery → Planhat | Nightly |
| CSM / AE owner | Salesforce | SFDC → Planhat | Nightly |
| Customer health score | Planhat | Planhat → SFDC (read-only field) | Real-time webhook |
| Health tier (Red/Amber/Green) | Planhat | Planhat → SFDC | Real-time webhook |
| Churn risk flag | BigQuery / Planhat | Planhat → SFDC | Real-time webhook |
| Product usage signals | Product DB | Product DB → BigQuery → Planhat | Daily |
| NPS score | Planhat | Planhat → BigQuery | Nightly |
| Support tickets / CSAT | Zendesk | Zendesk → BigQuery | Hourly |
| Company master (name, country) | Salesforce | SFDC → Planhat (via `externalId`) | Nightly |

**Design principle:** Salesforce is master for commercial data. Planhat is master for
health and lifecycle data. BigQuery is the analytical join layer.

---

## Key Salesforce Objects

### Account

Primary company record. The `Id` field is used as `externalId` in Planhat for
bi-directional linking.

| SFDC Field | API Name | Type | Maps To | Notes |
|---|---|---|---|---|
| Account ID | `Id` | ID | `planhat_external_id`, `customer_id` | Primary join key across all systems |
| Account Name | `Name` | string | `company_name` | |
| Account Owner | `OwnerId` | lookup | `ae_owner` | AE - not the same as CSM |
| CSM Owner | `CSM_Owner__c` | lookup | `csm_owner` | Custom field - lookup to User |
| Billing Country | `BillingCountry` | string | `country` | Normalise to ISO 3166-1 alpha-2 |
| Industry | `Industry` | picklist | `industry` | |
| Customer Segment | `Customer_Segment__c` | picklist | `segment` | Custom: `SMB`, `Mid-Market`, `Enterprise` |
| Fleet Size | `Fleet_Size__c` | number | `vehicle_count` | Custom - vehicle count at contract |
| Account Type | `Type` | picklist | — | Filter on `Customer` for active accounts |
| Health Score | `Planhat_Health_Score__c` | number | - | Read-only, written by Planhat webhook |
| Health Tier | `Planhat_Health_Tier__c` | picklist | - | `Green`, `Amber`, `Red` - written by Planhat |
| Churn Risk Flag | `Churn_Risk_Flag__c` | checkbox | - | Written by Planhat or our BigQuery model |
| Legacy System | `Legacy_System__c` | picklist | `legacy_system` | `Vimcar`, `Avrios`, `Optimum Automotive`, `New Logo` |

---

### Opportunity

Renewal and expansion tracking. Each renewal is a separate Opportunity record.

| SFDC Field | API Name | Type | Maps To | Notes |
|---|---|---|---|---|
| Opportunity ID | `Id` | ID | `opportunity_id` | |
| Account | `AccountId` | lookup | `customer_id` | Join key to Account |
| Opportunity Name | `Name` | string | - | Convention: `[Account] - Renewal - [Year]` |
| Stage | `StageName` | picklist | `renewal_stage` | Track: `Renewal Identified` → `In Negotiation` → `Closed Won/Lost` |
| Close Date | `CloseDate` | date | `renewal_date` | This is the canonical renewal date field |
| Amount | `Amount` | currency | `renewal_arr` | ARR value at renewal |
| Type | `Type` | picklist | - | Filter on `Existing Business - Renewal` |
| Renewal Probability | `Probability` | percent | `renewal_probability` | Override with our model output where available |
| Forecast Category | `ForecastCategoryName` | string | - | `Commit`, `Best Case`, `Pipeline`, `Omitted` |
| ARR Change | `ARR_Change__c` | currency | `expansion_arr` | Custom: positive = expansion, negative = contraction |
| Churn Reason | `Churn_Reason__c` | picklist | - | Custom: populate on Closed Lost |

**Renewal pipeline query (SOQL):**
```sql
SELECT Id, AccountId, Name, StageName, CloseDate, Amount, ARR_Change__c
FROM Opportunity
WHERE Type = 'Existing Business - Renewal'
  AND CloseDate >= TODAY
  AND CloseDate <= NEXT_N_DAYS:90
  AND IsClosed = false
ORDER BY CloseDate ASC
```

---

### Contract

The signed contract record. Source of truth for contract start/end dates and
initial ARR. More reliable than Opportunity for historical ARR analysis.

| SFDC Field | API Name | Type | Maps To | Notes |
|---|---|---|---|---|
| Contract ID | `Id` | ID | `contract_id` | |
| Account | `AccountId` | lookup | `customer_id` | |
| Status | `Status` | picklist | — | Filter on `Activated` |
| Contract Start Date | `StartDate` | date | `contract_start_date` | |
| Contract End Date | `EndDate` | date | `contract_end_date` | |
| Contract Term | `ContractTerm` | number | `contract_term_months` | In months |
| Annual Value | `Annual_Contract_Value__c` | currency | `arr` | Custom ACV field |
| Products | `SBQQ__Quote__c` | lookup | `products` | If using Salesforce CPQ |

---

### Task / Activity

CSM activity log in SFDC. Secondary source for QBR tracking, Planhat Tasks
are the primary source. Use SFDC Tasks for audit trail and manager visibility.

| SFDC Field | API Name | Type | Notes |
|---|---|---|---|
| Subject | `Subject` | string | Filter on `QBR` or `Executive Business Review` |
| Account | `AccountId` | lookup | |
| Status | `Status` | picklist | `Completed` = done |
| Activity Date | `ActivityDate` | date | |
| Description | `Description` | textarea | Capture QBR outcomes here |

---

## Integration Sync Logic

### Nightly SFDC → BigQuery Extract

Recommended: Salesforce Change Data Capture (CDC) events streamed to BigQuery via
Pub/Sub, or scheduled SOQL export using the Bulk API 2.0.

**Objects to extract nightly:**
- `Account` (full refresh — small volume)
- `Opportunity` (incremental by `LastModifiedDate`)
- `Contract` (incremental by `LastModifiedDate`)

**BigQuery landing tables:**
```
raw_salesforce.accounts
raw_salesforce.opportunities
raw_salesforce.contracts
```

### Planhat → SFDC Health Sync (Real-time)

Configure Planhat outbound webhook on `health` score change events.
Webhook payload updates `Planhat_Health_Score__c` and `Planhat_Health_Tier__c`
on the matching Account (matched via `externalId` = SFDC Account `Id`).

Trigger a Salesforce Flow on `Planhat_Health_Tier__c` change to:
- Create a Task for CSM when tier changes to `Red`
- Update Opportunity `Forecast Category` to `Omitted` when tier = `Red` + renewal < 90 days

### Field Conflict Resolution

When the same field exists in both SFDC and Planhat:

| Field | Winner | Resolution |
|---|---|---|
| `renewal_date` | Salesforce | Planhat syncs from SFDC nightly; never write renewal date from Planhat |
| `mrr` | Salesforce | Planhat `mr` field populated from SFDC Contract ACV / 12 |
| `csm_owner` | Salesforce | Planhat User synced from SFDC User lookup |
| `health_score` | Planhat | SFDC field is read-only; written by webhook only |
| `company_name` | Salesforce | Planhat syncs from SFDC Account Name |
