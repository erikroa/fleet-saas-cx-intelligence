"""
generate_data.py
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import random
import os

random.seed(42)
np.random.seed(42)

# Configuration 

N_CUSTOMERS = 250
REFERENCE_DATE = datetime(2024, 12, 31)

SEGMENTS = {
    "SMB":         {"weight": 0.55, "vehicle_range": (2, 20),   "mrr_per_vehicle": (18, 28)},
    "Mid-Market":  {"weight": 0.30, "vehicle_range": (21, 80),  "mrr_per_vehicle": (15, 22)},
    "Enterprise":  {"weight": 0.15, "vehicle_range": (81, 400), "mrr_per_vehicle": (12, 18)},
}

COUNTRIES = {"DE": 0.65, "AT": 0.20, "CH": 0.15}

INDUSTRIES = {
    "DE": ["Handwerk & Baugewerbe", "Logistik & Transport", "Facility Management",
           "Außendienst & Vertrieb", "Kommunaler Betrieb", "Gesundheitswesen"],
    "AT": ["Handwerk & Baugewerbe", "Logistik & Transport", "Facility Management",
           "Außendienst & Vertrieb"],
    "CH": ["Logistik & Transport", "Facility Management", "Außendienst & Vertrieb",
           "Baugewerbe"],
}

PRODUCTS = ["GPS Tracking", "Digital Logbook", "Fleet Analytics", "Driver Scoring"]

LEGACY_SYSTEMS = ["Vimcar", "Avrios", "Optimum Automotive", "New Logo"]

# Helper functions 
def weighted_choice(options: dict):
    keys = list(options.keys())
    weights = list(options.values())
    return random.choices(keys, weights=weights, k=1)[0]

def random_date(start_days_ago: int, end_days_ago: int) -> datetime:
    delta = random.randint(end_days_ago, start_days_ago)
    return REFERENCE_DATE - timedelta(days=delta)

def contract_start_date(segment: str) -> datetime:
    """Post-merger customers skew newer; legacy customers can be older."""
    if segment == "SMB":
        return random_date(1095, 30)   # up to 3 years
    elif segment == "Mid-Market":
        return random_date(1460, 60)   # up to 4 years
    else:
        return random_date(1825, 90)   # up to 5 years

# Customer master data

def generate_customers() -> pd.DataFrame:
    records = []
    seg_choices = random.choices(
        list(SEGMENTS.keys()),
        weights=[v["weight"] for v in SEGMENTS.values()],
        k=N_CUSTOMERS
    )
    country_choices = random.choices(
        list(COUNTRIES.keys()),
        weights=list(COUNTRIES.values()),
        k=N_CUSTOMERS
    )

    for i, (seg, country) in enumerate(zip(seg_choices, country_choices)):
        cfg = SEGMENTS[seg]
        vehicle_count = random.randint(*cfg["vehicle_range"])
        mrr_per_v = random.uniform(*cfg["mrr_per_vehicle"])
        mrr = round(vehicle_count * mrr_per_v, 2)

        start_date = contract_start_date(seg)
        tenure_months = max(1, (REFERENCE_DATE - start_date).days // 30)

        # Renewal date
        months_into_year = tenure_months % 12
        months_to_renewal = 12 - months_into_year if months_into_year > 0 else 12
        renewal_date = REFERENCE_DATE + timedelta(days=months_to_renewal * 30)

        # Legacy system (post-merger context)
        if start_date < datetime(2023, 1, 1):
            legacy_weight = [0.35, 0.30, 0.25, 0.10]
        else:
            legacy_weight = [0.10, 0.10, 0.05, 0.75]
        legacy_system = random.choices(LEGACY_SYSTEMS, weights=legacy_weight, k=1)[0]

        products = ["GPS Tracking"]  # all customers have GPS
        if vehicle_count >= 5:
            products.append("Digital Logbook")
        if seg in ("Mid-Market", "Enterprise"):
            products.append("Fleet Analytics")
        if seg == "Enterprise" and random.random() > 0.4:
            products.append("Driver Scoring")

        industry = random.choice(INDUSTRIES[country])

        # Churn risk signal
        base_churn_risk = 0.10  # baseline 10%

        risk_factors = 0
        if tenure_months < 6:      risk_factors += 0.15   # new, not yet sticky
        if seg == "SMB":           risk_factors += 0.08   # price sensitivity
        if legacy_system != "New Logo": risk_factors += 0.06  # migration friction
        if vehicle_count < 5:      risk_factors += 0.10   # low depth/stickiness
        if months_to_renewal <= 3: risk_factors += 0.05   # renewal window pressure
        if country == "CH":        risk_factors += 0.03   # higher alternatives

        # Reduce risk for long tenured + multi-product
        risk_factors -= min(0.15, tenure_months * 0.003)
        risk_factors -= len(products) * 0.04

        latent_churn_prob = min(0.85, max(0.02, base_churn_risk + risk_factors))

        records.append({
            "customer_id": f"CUST-{i+1:04d}",
            "segment": seg,
            "country": country,
            "industry": industry,
            "vehicle_count": vehicle_count,
            "mrr": mrr,
            "arr": round(mrr * 12, 2),
            "products": "|".join(products),
            "product_count": len(products),
            "legacy_system": legacy_system,
            "contract_start_date": start_date.date(),
            "tenure_months": tenure_months,
            "renewal_date": renewal_date.date(),
            "months_to_renewal": months_to_renewal,
            "_latent_churn_prob": latent_churn_prob,  # internal, drives usage
        })

    return pd.DataFrame(records)

# Customer archetypes

ARCHETYPES = {
    # (weight, gps_mean, gps_sd, login_exp_scale, dau_mau_mean, tickets_lambda,
    #  res_days_mean, csat_mean, csat_sd, qbr_prob, nps_pool, onboard_mean)
    "champion":   (0.20, 94, 4,  4,  0.55, 0.1, 1.5, 4.7, 0.3, 0.90, [8,9,9,10,10], 95),
    "healthy":    (0.25, 86, 6,  8,  0.40, 0.3, 2.5, 4.2, 0.4, 0.70, [7,8,8,9,9],   82),
    "drifting":   (0.20, 72, 9,  20, 0.28, 0.8, 5.0, 3.5, 0.5, 0.45, [5,6,6,7,8],   65),
    "struggling": (0.20, 55, 12, 38, 0.18, 1.8, 9.0, 2.8, 0.6, 0.20, [2,3,4,5,6],   45),
    "critical":   (0.15, 38, 14, 65, 0.08, 3.5, 16,  2.0, 0.7, 0.05, [0,1,1,2,3],   25),
}

def generate_health_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    Generate usage, support, and engagement signals using customer archetypes.
    Archetypes are assigned by percentile rank of latent churn probability,
    ensuring a realistic distribution: ~20% champion, ~25% healthy,
    ~25% drifting, ~20% struggling, ~10% critical.
    """
    archetype_names = list(ARCHETYPES.keys())
    target_pcts = [0.20, 0.25, 0.25, 0.20, 0.10]  # champion → critical

    # Assign archetypes by percentile of churn risk (ascending)
    df = df.copy().reset_index(drop=True)
    df["_rank"] = df["_latent_churn_prob"].rank(method="first", ascending=True)
    n = len(df)
    cutoffs = [0] + [int(n * sum(target_pcts[:i+1])) for i in range(len(target_pcts))]

    archetype_map = {}
    sorted_ids = df.sort_values("_rank")["customer_id"].tolist()
    for i, name in enumerate(archetype_names):
        for cid in sorted_ids[cutoffs[i]:cutoffs[i+1]]:
            archetype_map[cid] = name

    rows = []
    for _, c in df.iterrows():
        archetype = archetype_map.get(c["customer_id"], "healthy")
        (_, gps_m, gps_sd, login_scale, dau_m,
         tickets_lambda, res_m, csat_m, csat_sd, qbr_p, nps_pool, ob_m) = ARCHETYPES[archetype]

        # Adoption signals
        gps_adoption_pct = round(np.clip(np.random.normal(gps_m, gps_sd), 5, 100), 1)

        if "Digital Logbook" in c["products"]:
            logbook_completion_pct = round(np.clip(
                np.random.normal(gps_m * 0.95, gps_sd + 5), 5, 100
            ), 1)
        else:
            logbook_completion_pct = None

        expected_reports = c["product_count"] * 3
        usage_factor = gps_m / 92.0
        reports_generated_30d = max(0, int(np.random.normal(expected_reports * usage_factor, 2)))

        # Engagement signals
        days_since_login = min(120, max(1, int(np.random.exponential(login_scale))))
        mobile_dau_mau = round(np.clip(np.random.normal(dau_m, 0.10), 0.0, 0.85), 3)

        onboarding_base = ob_m
        tenure_boost = min(20, c["tenure_months"] * 0.5)
        onboarding_score = round(np.clip(
            np.random.normal(onboarding_base + tenure_boost, 8), 0, 100
        ), 1)

        # Support signals 
        open_tickets = max(0, int(np.random.poisson(tickets_lambda)))
        avg_resolution_days = round(np.clip(np.random.normal(res_m, res_m * 0.3), 0.5, 45), 1)
        csat_score = round(np.clip(np.random.normal(csat_m, csat_sd), 1.0, 5.0), 1)

        # Relationship signals
        qbr_done = 1 if (c["segment"] in ("Enterprise", "Mid-Market") and
                         random.random() < qbr_p) else 0
        surveyed = random.random() < 0.65
        nps_score = None
        if surveyed:
            nps_score = random.choice(nps_pool)

        # Expansion signals 
        expansion_mrr_3m = 0.0
        if archetype in ("champion", "healthy") and c["tenure_months"] >= 6:
            if random.random() < 0.28:
                expansion_pct = random.uniform(0.06, 0.28)
                expansion_mrr_3m = round(c["mrr"] * expansion_pct, 2)

        rows.append({
            "customer_id": c["customer_id"],
            "archetype": archetype,
            "gps_adoption_pct": gps_adoption_pct,
            "logbook_completion_pct": logbook_completion_pct,
            "reports_generated_30d": reports_generated_30d,
            "days_since_last_login": days_since_login,
            "mobile_dau_mau": mobile_dau_mau,
            "open_support_tickets": open_tickets,
            "avg_ticket_resolution_days": avg_resolution_days,
            "csat_score": csat_score,
            "qbr_completed_this_quarter": qbr_done,
            "nps_score": nps_score,
            "onboarding_completion_score": onboarding_score,
            "expansion_mrr_3m": expansion_mrr_3m,
            "as_of_date": REFERENCE_DATE.date(),
        })

    return pd.DataFrame(rows)

# Monthly MRR history (for NRR/GRR calculation)

def generate_monthly_mrr(df: pd.DataFrame) -> pd.DataFrame:
    """
    Generate 12 months of MRR history per customer.
    Captures churn, contraction, and expansion events.
    """
    records = []
    months = pd.date_range(end=REFERENCE_DATE, periods=12, freq="MS")

    for _, c in df.iterrows():
        p = c["_latent_churn_prob"]
        current_mrr = c["mrr"]
        churned = False
        churned_month = None

        # Determine if this customer churned in the lookback window
        # Only ~15% actually churn in any 12m window (realistic for fleet SaaS)
        actual_churned = random.random() < (p * 0.18)
        if actual_churned:
            churn_month_idx = random.randint(6, 11)  # churned in H2 of the year
        else:
            churn_month_idx = None

        mrr_at_start = current_mrr * random.uniform(0.75, 0.95)  # backfill start MRR

        for idx, month in enumerate(months):
            if churn_month_idx is not None and idx >= churn_month_idx:
                mrr = 0.0
                churned = True
            else:
                # Apply small MRR drift: expansion or contraction
                if idx == 0:
                    mrr = mrr_at_start
                else:
                    if random.random() < 0.12 and not churned:  # 12% expansion probability
                        mrr = mrr * random.uniform(1.05, 1.20)
                    elif random.random() < 0.05 and not churned:  # 5% contraction
                        mrr = mrr * random.uniform(0.80, 0.95)

                mrr = round(mrr, 2)

            records.append({
                "customer_id": c["customer_id"],
                "month": month.date(),
                "mrr": mrr,
                "churned": 1 if (churned and idx == churn_month_idx) else 0,
            })

    return pd.DataFrame(records)


# Main 

if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)

    print("Generating customer master data...")
    customers = generate_customers()

    print("Generating health & usage signals...")
    health = generate_health_signals(customers)

    print("Generating monthly MRR history...")
    monthly = generate_monthly_mrr(customers)

    # Drop internal column before saving
    customers_out = customers.drop(columns=["_latent_churn_prob"])

    customers_out.to_csv("data/customers.csv", index=False)
    health.to_csv("data/customer_health_signals.csv", index=False)
    monthly.to_csv("data/monthly_mrr.csv", index=False)

    print(f"\n✓ Generated {len(customers_out)} customers")
    print(f"✓ Segments: {customers_out['segment'].value_counts().to_dict()}")
    print(f"✓ Countries: {customers_out['country'].value_counts().to_dict()}")
    print(f"✓ Total ARR: €{customers_out['arr'].sum():,.0f}")
    print(f"✓ Monthly MRR rows: {len(monthly):,}")
    print("\nFiles written:")
    print("  data/customers.csv")
    print("  data/customer_health_signals.csv")
    print("  data/monthly_mrr.csv")
