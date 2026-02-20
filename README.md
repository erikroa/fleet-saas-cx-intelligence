# Fleet SaaS CX Operations Intelligence

> A CX Operations analytics project built to demonstrate operator-level thinking in fleet management SaaS.
> Designed for a post-merger, PE-backed context with a DACH customer base.

---

## The Business Question

**In a post-merger fleet SaaS environment scaling across DACH, which customers are at risk of churning at their next renewal, and what is the NRR impact if CS doesn't act in the next 90 days?**

This project exists because health scores without revenue context don't drive action. Most CS teams know they have at-risk customers; what they need is a prioritised, ARR-weighted intervention list tied to observable product signals.

---

## Context

Fleet management SaaS has operational stakes that most SaaS categories don't: customers use the product every day, across every vehicle in their fleet. When GPS adoption drops or logbook compliance falls, it's a sign that drivers have stopped complying with fleet policy, and the customer is no longer getting the regulatory and cost benefits they paid for.

Post-merger, this signal is harder to read: legacy customers from multiple systems (3 different Automotives) have different benchmarks, different onboarding histories, and different product surfaces. A unified health scoring model needs to work across all of them.

---

## What This Project Covers

| Module | What It Does | Business Output |
|--------|--------------|-----------------|
| `data/generate_data.py` | Synthetic DACH fleet SaaS customer dataset | 250 customers, €3M ARR, 12 months MRR history |
| `models/health_scoring.py` | Four-dimension Planhat-style health model | Customer health tiers + churn risk flags |
| `analysis/retention_analysis.py` | NRR/GRR calculation + renewal pipeline | 90-day ARR-at-risk: €108K across 38 accounts |
| `dashboards/executive_dashboard.py` | 6-panel matplotlib executive dashboard | Board-ready CX ops overview |

---

## Health Scoring Model

Health is calculated across four dimensions, each mapped to signals available in a standard Planhat + Salesforce + product analytics stack:

```
Health Score = (Adoption × 35%) + (Engagement × 30%) + (Support × 20%) + (Relationship × 15%)
```

### Dimension Design Rationale

**Adoption (35%)** - highest weight because it's the proxy for customer ROI. In fleet SaaS, a customer with 90%+ GPS adoption is extracting value from every tracked kilometre. Drop below 60% and drivers are working around the product, not with it.

- GPS active vehicle rate (% of fleet pinging in last 30d)
- Digital logbook completion rate (compliance for tax/GDPR purposes)
- Fleet reports generated (value realisation signal)

**Engagement (30%)** - admin login frequency and mobile DAU/MAU. The admin is the internal champion; if they stop logging in, sponsorship is eroding. Mobile DAU/MAU captures driver engagement — fleets with high driver adoption are structurally stickier.

- Days since last admin login
- Mobile app DAU/MAU ratio
- Onboarding completion score

**Support Health (20%)** - fleet operators are operationally sensitive. Unresolved tickets in a GPS tracking context mean vehicles aren't being tracked, logbooks are incomplete, or compliance is at risk. Resolution time >7 days is a red flag.

- Open ticket count
- Average ticket resolution time
- CSAT score

**Relationship (15%)** - executive sponsorship matters at renewal. QBR completion is a leading indicator: customers who engage in strategic reviews are 2× more likely to renew and expand.

- QBR completed this quarter (binary)
- NPS score (non-response treated as neutral, not zero)

### Health Tiers

| Tier | Score | Interpretation |
|------|-------|----------------|
| 🟢 Green | 70-100 | Healthy. Monitor for expansion signals. |
| 🟡 Amber | 40-69 | Early warning. CSM check-in required. |
| 🔴 Red | 0-39 | At risk. Immediate intervention needed. |

---

## Key Findings

### Portfolio Health (Q4 2024)

| Metric | Value |
|--------|-------|
| Total ARR | €3.06M |
| Customers | 250 |
| Trailing 3M NRR | 101.0% |
| Trailing 3M GRR | 99.5% |
| ARR at risk (90d renewal window) | €108,743 |
| Priority intervention accounts | 38 |

### The SMB Problem

The most significant finding is the segment divergence in health distribution:

| Segment | Red + Amber | ARR at Risk |
|---------|-------------|-------------|
| Enterprise | 4.8% | €0 |
| Mid-Market | 3.0% | €0 |
| **SMB** | **78.7%** | **€108,743** |

SMB health is being dragged down by three correlated signals: low GPS adoption (many fleets under 10 vehicles don't enforce driver compliance), long login gaps (owner-operators managing the account themselves, not a dedicated fleet manager), and incomplete onboarding.

This is a Planhat automation challenge: the SMB segment can't be covered by human CSMs at scale, so intervention needs to happen through lifecycle triggers.

### The Post-Merger Legacy Risk

Customers migrated from legacy systems (3 different Automotives) show lower onboarding completion scores and higher open ticket rates in the first 12 months post-migration. This is a change management signal. These customers need dedicated migration success plays.

---

## CS Intervention Framework

Based on the renewal pipeline analysis, intervention type is determined by risk × segment:

| Risk Level | Trigger | Intervention |
|------------|---------|--------------|
| **Critical** (Red + ≤3m to renewal) | ARR > €5K | Executive escalation + Emergency EBR |
| **High** (Amber + ≤3m) - Enterprise | Missed QBR | CSM-led QBR + Executive sponsor outreach |
| **High** (Amber + ≤3m) - SMB/MM | GPS adoption <55% | CSM check-in + product training session |
| **Medium** (Amber + 3-6m) | Login gap >30d | Automated check-in sequence + feature nudge |
| **Low** (Green) | Renewal approaching | Automated renewal + expansion play |

---

## Integration Layer

The `/integrations` folder documents how this analysis connects to a production CX Ops stack:

| File | What It Covers |
|---|---|
| `planhat_api_schema.md` | Planhat REST API objects, field mappings to our health model, pagination patterns, and known gotchas |
| `salesforce_field_mapping.md` | SFDC Account/Opportunity/Contract field mapping, system-of-record ownership, and sync direction per field |
| `planhat_to_bigquery_pipeline.py` | Extraction script - Planhat API → BigQuery with auth, pagination, rate limiting, and schema transforms |
| `data_model_diagram.md` | Full stack architecture: source systems → BigQuery raw → dbt staging/marts → Planhat/SFDC/Looker Studio |

---

## Technical Stack

```
Python 3.11
├── pandas / numpy          - data modelling and aggregation
├── matplotlib / seaborn    - executive dashboard visualisation
└── scikit-learn            - (available for predictive extension)

SQL layer (BigQuery-ready)
└── models/ contains scoring logic portable to dbt SQL models

Planhat integration points
└── Signals mapped to standard Planhat health dimension schema
    (adoption, engagement, support, relationship)
```

---

## Project Structure

```
fleet_saas_cx_intelligence/
│
├── data/
│   ├── generate_data.py              ← synthetic DACH fleet SaaS dataset
│   ├── customers.csv                 ← 250 customer master records
│   ├── customer_health_signals.csv   ← usage, support, engagement signals
│   ├── monthly_mrr.csv               ← 12-month MRR history per customer
│   ├── customer_health_scores.csv    ← scored output (all dimensions)
│   ├── nrr_grr_summary.csv           ← monthly NRR/GRR waterfall
│   ├── renewal_pipeline.csv          ← 9-month forward renewal view
│   ├── cs_intervention_list.csv      ← prioritised CS action list
│   ├── segment_health_summary.csv    ← exec-level segment roll-up
│   └── country_health_summary.csv    ← DACH country breakdown
│
├── models/
│   └── health_scoring.py             ← four-dimension health score model
│
├── analysis/
│   └── retention_analysis.py         ← NRR/GRR + renewal pipeline + CS list
│
├── dashboards/
│   ├── executive_dashboard.py        ← 6-panel executive dashboard
│   └── cx_ops_executive_dashboard.png
│
├── requirements.txt
└── README.md
```

---

## Running the Project

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Generate synthetic dataset
python data/generate_data.py

# 3. Compute health scores
python models/health_scoring.py

# 4. Run retention analysis
python analysis/retention_analysis.py

# 5. Render executive dashboard
python dashboards/executive_dashboard.py
```

---

## Extending to Production

This project is structured to mirror how this analysis would actually run in a production CX Ops stack:

**Data sources** → Planhat API (health signals), Salesforce (contract/ARR), product analytics (GPS/logbook usage), Zendesk/Intercom (support tickets), billing system (MRR/expansion).

**Scheduling** → Daily health score refresh in Planhat, weekly NRR/GRR recalculation in BigQuery, 90-day renewal pipeline reviewed in Monday morning CS standup.

**Automation** → Planhat lifecycle signals trigger CSM task creation in Salesforce when a customer crosses from Green→Amber, or when GPS adoption drops >15% week-over-week.

**Reporting** → The executive dashboard outputs replicate what would be built in Looker Studio as a live, connected report pulling from BigQuery views.

---

## About This Project

Built as part of a portfolio demonstrating CX Operations and RevOps analytical capabilities in B2B SaaS. Domain expertise: customer health modelling, and NRR/GRR analysis.

The dataset is synthetic and generated for illustrative purposes. All business logic reflects real-world CX Ops practice.
