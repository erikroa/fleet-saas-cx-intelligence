"""
health_scoring.py
-----------------
Implements a Planhat-style four-dimension customer health score for fleet SaaS.

Health model architecture (mirrors how Planhat segments scores):
    ┌──────────────────┬────────┬─────────────────────────────────────────────┐
    │ Dimension        │ Weight │ Signals                                     │
    ├──────────────────┼────────┼─────────────────────────────────────────────┤
    │ Product Adoption │  35%   │ GPS adoption %, logbook completion,         │
    │                  │        │ reports generated, product breadth          │
    ├──────────────────┼────────┼─────────────────────────────────────────────┤
    │ Engagement       │  30%   │ Days since login, mobile DAU/MAU,           │
    │                  │        │ onboarding completion                       │
    ├──────────────────┼────────┼─────────────────────────────────────────────┤
    │ Support Health   │  20%   │ Open tickets, resolution time, CSAT         │
    ├──────────────────┼────────┼─────────────────────────────────────────────┤
    │ Relationship     │  15%   │ QBR completion, NPS score                   │
    └──────────────────┴────────┴─────────────────────────────────────────────┘

Output:
    - health_score: 0-100 composite score
    - health_tier: Red (0-39) / Amber (40-69) / Green (70-100)
    - dimension scores for drill-down
    - churn_risk_flag: priority intervention flag for CS team

Usage:
    python models/health_scoring.py
    → Writes data/customer_health_scores.csv
"""

import pandas as pd
import numpy as np
import os

# Dimension weights

WEIGHTS = {
    "adoption":     0.35,
    "engagement":   0.30,
    "support":      0.20,
    "relationship": 0.15,
}

assert sum(WEIGHTS.values()) == 1.0, "Weights must sum to 1"

# Scoring (each returns 0-100) 

def score_adoption(row: pd.Series) -> float:
    """
    Product adoption score. Fleet SaaS adoption = vehicles actively tracked
    + logbook compliance + breadth of product usage.
    """
    scores = []

    # GPS adoption: linear scale, 80%+ = full score
    gps = row["gps_adoption_pct"]
    gps_score = np.clip(gps / 80 * 100, 0, 100)
    scores.append(("gps", gps_score, 0.50))

    # Logbook completion (only if product active)
    if pd.notna(row["logbook_completion_pct"]):
        lb = row["logbook_completion_pct"]
        lb_score = np.clip(lb / 85 * 100, 0, 100)
        scores.append(("logbook", lb_score, 0.25))
    else:
        # No logbook product: redistribute weight to GPS
        scores[0] = ("gps", gps_score, 0.75)

    # Reports generated: proxy for value realization
    reports = row["reports_generated_30d"]
    # Benchmark: expect ~3 reports/product/month
    expected = row.get("product_count", 1) * 3
    report_score = np.clip(reports / max(expected, 1) * 100, 0, 100)
    scores.append(("reports", report_score, 0.25))

    # Weighted sum
    total_weight = sum(s[2] for s in scores)
    return sum(s[1] * s[2] for s in scores) / total_weight


def score_engagement(row: pd.Series) -> float:
    """
    Platform engagement. Admin logins + mobile adoption signal customer
    is deriving ongoing value — not just 'set and forget'.
    """
    # Days since last login: exponential decay curve
    days = row["days_since_last_login"]
    if days <= 3:
        login_score = 100
    elif days <= 7:
        login_score = 90
    elif days <= 14:
        login_score = 70
    elif days <= 30:
        login_score = 45
    elif days <= 60:
        login_score = 20
    else:
        login_score = 5

    # Mobile DAU/MAU: 0.4+ is healthy for fleet drivers
    dau_mau = row["mobile_dau_mau"]
    mobile_score = np.clip(dau_mau / 0.40 * 100, 0, 100)

    # Onboarding completion: unlocks value realization
    onboarding = row["onboarding_completion_score"]
    onboarding_score = np.clip(onboarding, 0, 100)

    return (login_score * 0.40) + (mobile_score * 0.35) + (onboarding_score * 0.25)


def score_support(row: pd.Series) -> float:
    """
    Support health score. Unresolved tickets and slow resolution are
    leading indicators of churn in fleet SaaS (high-urgency operations context).
    """
    # Open tickets: penalty increases non-linearly
    tickets = row["open_support_tickets"]
    if tickets == 0:
        ticket_score = 100
    elif tickets == 1:
        ticket_score = 75
    elif tickets == 2:
        ticket_score = 50
    elif tickets <= 4:
        ticket_score = 25
    else:
        ticket_score = 5

    # Resolution time: >7 days is a red flag in fleet ops
    res_days = row["avg_ticket_resolution_days"]
    if res_days <= 1:
        resolution_score = 100
    elif res_days <= 3:
        resolution_score = 85
    elif res_days <= 7:
        resolution_score = 60
    elif res_days <= 14:
        resolution_score = 30
    else:
        resolution_score = 10

    # CSAT: 1–5 scale normalised to 0–100
    csat = row["csat_score"]
    csat_score = (csat - 1) / 4 * 100

    return (ticket_score * 0.40) + (resolution_score * 0.30) + (csat_score * 0.30)


def score_relationship(row: pd.Series) -> float:
    """
    Executive/strategic relationship score. QBRs and NPS indicate whether
    CS has a healthy sponsor relationship — critical for renewal decisions.
    """
    # QBR completion (binary, weighted heavily for Mid-Market/Enterprise)
    qbr_score = 100 if row["qbr_completed_this_quarter"] == 1 else 20

    # NPS: convert to 0–100 scale; no response = neutral (50)
    nps = row["nps_score"]
    if pd.isna(nps):
        nps_score = 50  # no response = unknown, not zero
    else:
        nps_score = np.clip((nps / 10) * 100, 0, 100)

    return (qbr_score * 0.60) + (nps_score * 0.40)


# Composite health score

def compute_health_scores(customers: pd.DataFrame, signals: pd.DataFrame) -> pd.DataFrame:
    df = customers.merge(signals, on="customer_id", how="left")

    df["adoption_score"]     = df.apply(score_adoption, axis=1).round(1)
    df["engagement_score"]   = df.apply(score_engagement, axis=1).round(1)
    df["support_score"]      = df.apply(score_support, axis=1).round(1)
    df["relationship_score"] = df.apply(score_relationship, axis=1).round(1)

    df["health_score"] = (
        df["adoption_score"]     * WEIGHTS["adoption"]   +
        df["engagement_score"]   * WEIGHTS["engagement"] +
        df["support_score"]      * WEIGHTS["support"]    +
        df["relationship_score"] * WEIGHTS["relationship"]
    ).round(1)

    # Health tier classification
    def tier(score):
        if score >= 70:
            return "Green"
        elif score >= 40:
            return "Amber"
        else:
            return "Red"

    df["health_tier"] = df["health_score"].apply(tier)

    # Churn risk flag: renewal urgency × health 
    # Priority intervention = Red/Amber health AND renewing in 90 days
    df["renewal_in_90d"] = df["months_to_renewal"] <= 3
    df["churn_risk_flag"] = (
        (df["health_tier"].isin(["Red", "Amber"])) &
        (df["renewal_in_90d"])
    )

    # At-risk ARR
    df["at_risk_arr"] = df.apply(
        lambda r: r["arr"] if r["churn_risk_flag"] else 0.0, axis=1
    )

    return df

# Output columns

OUTPUT_COLS = [
    "customer_id", "segment", "country", "industry",
    "vehicle_count", "mrr", "arr",
    "products", "product_count", "legacy_system",
    "contract_start_date", "tenure_months", "renewal_date", "months_to_renewal",
    # Health dimensions
    "adoption_score", "engagement_score", "support_score", "relationship_score",
    "health_score", "health_tier",
    # Signals (key ones for drill-down)
    "gps_adoption_pct", "logbook_completion_pct", "days_since_last_login",
    "mobile_dau_mau", "open_support_tickets", "csat_score",
    "qbr_completed_this_quarter", "nps_score", "onboarding_completion_score",
    "expansion_mrr_3m",
    # Risk flags
    "renewal_in_90d", "churn_risk_flag", "at_risk_arr",
]

# Main

if __name__ == "__main__":
    customers = pd.read_csv("data/customers.csv")
    signals   = pd.read_csv("data/customer_health_signals.csv")

    print("Computing health scores...")
    scored = compute_health_scores(customers, signals)
    scored = scored[OUTPUT_COLS]

    scored.to_csv("data/customer_health_scores.csv", index=False)

    print(f"\n✓ Health score distribution:")
    tier_counts = scored["health_tier"].value_counts()
    for tier in ["Green", "Amber", "Red"]:
        count = tier_counts.get(tier, 0)
        arr = scored[scored["health_tier"] == tier]["arr"].sum()
        print(f"  {tier:6s}: {count:3d} customers | ARR €{arr:,.0f}")

    at_risk = scored[scored["churn_risk_flag"]]
    print(f"\n✓ Churn risk flagged (Red/Amber + renewing in 90d):")
    print(f"  {len(at_risk)} customers | ARR at risk: €{at_risk['arr'].sum():,.0f}")
    print(f"\n  Written → data/customer_health_scores.csv")
