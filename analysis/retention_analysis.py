"""
Outputs:
    data/nrr_grr_summary.csv         - Monthly NRR/GRR calculated from history
    data/renewal_pipeline.csv        - Upcoming renewals with risk classification
    data/cs_intervention_list.csv    - Prioritised CS actions for Q1 2025
    data/segment_health_summary.csv  - Segment-level health roll-up (exec view)
"""

import pandas as pd
import numpy as np
import os

REFERENCE_DATE = pd.Timestamp("2024-12-31")

# Load data 

def load_data():
    scored    = pd.read_csv("data/customer_health_scores.csv", parse_dates=["renewal_date"])
    monthly   = pd.read_csv("data/monthly_mrr.csv", parse_dates=["month"])
    return scored, monthly

# NRR / GRR calculation 

def calculate_nrr_grr(monthly: pd.DataFrame) -> pd.DataFrame:
    """
    Calculates monthly Net Revenue Retention and Gross Revenue Retention
    using a rolling 12-month cohort approach.

    NRR = (Starting MRR + Expansion MRR - Churn MRR - Contraction MRR)
          / Starting MRR

    GRR = (Starting MRR - Churn MRR - Contraction MRR)
          / Starting MRR  (expansion excluded; floors at 0)
    """
    monthly = monthly.sort_values(["customer_id", "month"])

    # Pivot to customer × month
    pivot = monthly.pivot_table(
        index="customer_id", columns="month", values="mrr", fill_value=0
    )
    months = sorted(pivot.columns)

    records = []
    for i in range(1, len(months)):
        prev_month = months[i - 1]
        curr_month = months[i]

        # Cohort: customers who had MRR in the previous month
        cohort = pivot[pivot[prev_month] > 0]
        starting_mrr = cohort[prev_month].sum()

        if starting_mrr == 0:
            continue

        curr_mrr = cohort[curr_month]
        prev_mrr = cohort[prev_month]

        churned_mrr     = prev_mrr[curr_mrr == 0].sum()         # churned to 0
        contracted_mrr  = (prev_mrr - curr_mrr)[(curr_mrr > 0) & (curr_mrr < prev_mrr)].sum()
        expanded_mrr    = (curr_mrr - prev_mrr)[curr_mrr > prev_mrr].sum()
        retained_mrr    = curr_mrr[(curr_mrr > 0) & (curr_mrr <= prev_mrr)].sum()

        ending_mrr_grr  = starting_mrr - churned_mrr - contracted_mrr
        ending_mrr_nrr  = ending_mrr_grr + expanded_mrr

        grr = ending_mrr_grr / starting_mrr
        nrr = ending_mrr_nrr / starting_mrr

        records.append({
            "month": curr_month,
            "starting_mrr":    round(starting_mrr, 2),
            "churned_mrr":     round(churned_mrr, 2),
            "contracted_mrr":  round(contracted_mrr, 2),
            "expanded_mrr":    round(expanded_mrr, 2),
            "retained_mrr":    round(retained_mrr, 2),
            "ending_mrr":      round(ending_mrr_nrr, 2),
            "grr":             round(grr, 4),
            "nrr":             round(nrr, 4),
            "customers_churned": int((curr_mrr == 0).sum()),
            "customers_expanded": int((curr_mrr > prev_mrr).sum()),
        })

    return pd.DataFrame(records)


# Renewal pipeline analysis

def build_renewal_pipeline(scored: pd.DataFrame) -> pd.DataFrame:
    """
    Builds a 90-day forward-looking renewal pipeline with risk classification,
    expected revenue impact, and recommended intervention type.
    """
    pipeline = scored[scored["months_to_renewal"] <= 9].copy()
    pipeline = pipeline.sort_values("months_to_renewal")

    # Risk classification: combines health tier + urgency
    def classify_risk(row):
        tier  = row["health_tier"]
        m2r   = row["months_to_renewal"]
        if tier == "Red":
            return "Critical" if m2r <= 3 else "High"
        elif tier == "Amber":
            return "High" if m2r <= 3 else "Medium"
        else:
            return "Low"

    pipeline["renewal_risk"] = pipeline.apply(classify_risk, axis=1)

    # Expected renewal outcome: probability of renewing based on risk
    renewal_prob_map = {"Critical": 0.30, "High": 0.55, "Medium": 0.75, "Low": 0.92}
    pipeline["renewal_probability"] = pipeline["renewal_risk"].map(renewal_prob_map)
    pipeline["expected_renewal_arr"] = (pipeline["arr"] * pipeline["renewal_probability"]).round(2)
    pipeline["arr_at_risk"] = (pipeline["arr"] * (1 - pipeline["renewal_probability"])).round(2)

    # Expansion opportunity (from current expansion signal)
    pipeline["expansion_potential_arr"] = (pipeline["expansion_mrr_3m"] * 12).round(2)

    # Recommended intervention type
    def intervention_type(row):
        risk = row["renewal_risk"]
        seg  = row["segment"]
        if risk == "Critical":
            return "Executive Escalation + Emergency EBR"
        elif risk == "High" and seg == "Enterprise":
            return "CSM-led QBR + Executive Sponsor Outreach"
        elif risk == "High":
            return "CSM-led Health Review + Product Training"
        elif risk == "Medium":
            return "CSM Check-in + Feature Adoption Nudge"
        else:
            return "Automated Renewal Sequence + Expansion Play"

    pipeline["recommended_intervention"] = pipeline.apply(intervention_type, axis=1)

    return pipeline[[
        "customer_id", "segment", "country", "legacy_system",
        "vehicle_count", "mrr", "arr",
        "health_score", "health_tier", "renewal_risk",
        "months_to_renewal", "renewal_date",
        "renewal_probability", "expected_renewal_arr", "arr_at_risk",
        "expansion_potential_arr",
        "gps_adoption_pct", "days_since_last_login",
        "open_support_tickets", "csat_score", "qbr_completed_this_quarter",
        "recommended_intervention",
    ]].sort_values(["renewal_risk", "arr_at_risk"], ascending=[True, False])


# CS intervention priority list 

def build_intervention_list(pipeline: pd.DataFrame) -> pd.DataFrame:
    """
    Produces an actionable list for CS team leaders.
    Focused on Critical and High risk accounts renewing in 90 days.
    Includes the single most important signal driving each flag.
    """
    priority = pipeline[
        (pipeline["renewal_risk"].isin(["Critical", "High"])) &
        (pipeline["months_to_renewal"] <= 3)
    ].copy()

    def primary_risk_signal(row):
        signals = []
        if row["gps_adoption_pct"] < 55:
            signals.append(f"GPS adoption {row['gps_adoption_pct']:.0f}% (below 70% threshold)")
        if row["days_since_last_login"] > 30:
            signals.append(f"No admin login in {row['days_since_last_login']:.0f} days")
        if row["open_support_tickets"] >= 3:
            signals.append(f"{int(row['open_support_tickets'])} open support tickets")
        if row["csat_score"] < 3.0:
            signals.append(f"CSAT {row['csat_score']:.1f}/5.0")
        if row["qbr_completed_this_quarter"] == 0 and row["segment"] in ("Enterprise", "Mid-Market"):
            signals.append("No QBR this quarter")
        return signals[0] if signals else "Multiple signals — see full health breakdown"

    priority["primary_risk_signal"] = priority.apply(primary_risk_signal, axis=1)
    priority["priority_rank"] = range(1, len(priority) + 1)

    return priority[[
        "priority_rank", "customer_id", "segment", "country",
        "arr", "arr_at_risk", "health_score", "health_tier", "renewal_risk",
        "months_to_renewal", "legacy_system",
        "primary_risk_signal", "recommended_intervention",
    ]]


# Segment health summary

def build_segment_summary(scored: pd.DataFrame) -> pd.DataFrame:
    """
    Segment-level health and revenue for executive dashboard.
    Answers: where is our retention risk concentrated by segment?
    """
    summary = scored.groupby("segment").agg(
        customers        = ("customer_id", "count"),
        total_arr        = ("arr", "sum"),
        avg_health_score = ("health_score", "mean"),
        green_count      = ("health_tier", lambda x: (x == "Green").sum()),
        amber_count      = ("health_tier", lambda x: (x == "Amber").sum()),
        red_count        = ("health_tier", lambda x: (x == "Red").sum()),
        at_risk_arr      = ("at_risk_arr", "sum"),
        churn_risk_customers = ("churn_risk_flag", "sum"),
        expansion_pipeline   = ("expansion_mrr_3m", lambda x: x.sum() * 12),
    ).round(2).reset_index()

    summary["pct_red_amber"] = (
        (summary["amber_count"] + summary["red_count"]) / summary["customers"] * 100
    ).round(1)

    summary["at_risk_pct_of_arr"] = (
        summary["at_risk_arr"] / summary["total_arr"] * 100
    ).round(1)

    return summary.sort_values("total_arr", ascending=False)


# Country health summary
def build_country_summary(scored: pd.DataFrame) -> pd.DataFrame:
    """DACH breakdown for regional CS team allocation."""
    summary = scored.groupby("country").agg(
        customers        = ("customer_id", "count"),
        total_arr        = ("arr", "sum"),
        avg_health_score = ("health_score", "mean"),
        at_risk_arr      = ("at_risk_arr", "sum"),
        red_count        = ("health_tier", lambda x: (x == "Red").sum()),
        amber_count      = ("health_tier", lambda x: (x == "Amber").sum()),
    ).round(2).reset_index()

    summary["at_risk_pct"] = (
        summary["at_risk_arr"] / summary["total_arr"] * 100
    ).round(1)

    return summary.sort_values("total_arr", ascending=False)


# Main 

if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)

    scored, monthly = load_data()

    # NRR / GRR
    print("Calculating NRR/GRR from 12-month MRR history...")
    nrr_grr = calculate_nrr_grr(monthly)
    nrr_grr.to_csv("data/nrr_grr_summary.csv", index=False)
    trailing_nrr = nrr_grr["nrr"].tail(3).mean()
    trailing_grr = nrr_grr["grr"].tail(3).mean()
    print(f"  Trailing 3-month avg NRR: {trailing_nrr:.1%}")
    print(f"  Trailing 3-month avg GRR: {trailing_grr:.1%}")

    # Renewal pipeline
    print("\nBuilding renewal pipeline...")
    pipeline = build_renewal_pipeline(scored)
    pipeline.to_csv("data/renewal_pipeline.csv", index=False)
    print(f"  {len(pipeline)} customers in 9-month pipeline")
    critical_high = pipeline[pipeline["renewal_risk"].isin(["Critical", "High"])]
    print(f"  Critical/High risk: {len(critical_high)} accounts | "
          f"ARR at risk: €{critical_high['arr_at_risk'].sum():,.0f}")

    # CS intervention list
    print("\nBuilding CS intervention list (90-day window)...")
    interventions = build_intervention_list(pipeline)
    interventions.to_csv("data/cs_intervention_list.csv", index=False)
    print(f"  {len(interventions)} priority accounts for immediate action")
    print(f"  Total ARR at stake: €{interventions['arr_at_risk'].sum():,.0f}")

    # Segment summary
    print("\nBuilding segment health summary...")
    seg_summary = build_segment_summary(scored)
    seg_summary.to_csv("data/segment_health_summary.csv", index=False)
    print(seg_summary[["segment", "customers", "total_arr",
                        "avg_health_score", "pct_red_amber", "at_risk_arr"]].to_string(index=False))

    # Country summary
    country_summary = build_country_summary(scored)
    country_summary.to_csv("data/country_health_summary.csv", index=False)

    print("\n✓ All analysis files written to data/")
