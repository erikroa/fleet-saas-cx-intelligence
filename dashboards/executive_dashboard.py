"""
executive_dashboard.py
----------------------
Generates an executive-ready CX Operations dashboard for fleet SaaS.
Designed to answer the questions a Head of RevOps asks in a Monday morning
pipeline review:

    1. What is our overall customer health posture?
    2. Where is churn risk concentrated — and what ARR is at stake?
    3. How are retention metrics (NRR/GRR) trending?
    4. Which segment/country needs CS attention this quarter?

Output:
    dashboards/cx_ops_executive_dashboard.png
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.gridspec as gridspec
from matplotlib.ticker import FuncFormatter
import warnings
import os

warnings.filterwarnings("ignore")
os.makedirs("dashboards", exist_ok=True)

# ── Palette ────────────────────────────────────────────────────────────────────
COLORS = {
    "green":       "#2ECC71",
    "amber":       "#F39C12",
    "red":         "#E74C3C",
    "blue":        "#2980B9",
    "dark_blue":   "#1A3A5C",
    "light_blue":  "#AED6F1",
    "grey":        "#95A5A6",
    "light_grey":  "#ECF0F1",
    "dark_grey":   "#2C3E50",
    "text":        "#2C3E50",
    "bg":          "#FAFAFA",
    "panel_bg":    "#FFFFFF",
}

TIER_COLORS = {
    "Green":  COLORS["green"],
    "Amber":  COLORS["amber"],
    "Red":    COLORS["red"],
}

RISK_COLORS = {
    "Critical": COLORS["red"],
    "High":     "#E67E22",
    "Medium":   COLORS["amber"],
    "Low":      COLORS["green"],
}

euro_fmt  = FuncFormatter(lambda x, _: f"€{x:,.0f}")
keur_fmt  = FuncFormatter(lambda x, _: f"€{x/1000:.0f}K")
pct_fmt   = FuncFormatter(lambda x, _: f"{x:.0%}")


def load_data():
    scored   = pd.read_csv("data/customer_health_scores.csv", parse_dates=["renewal_date"])
    nrr_grr  = pd.read_csv("data/nrr_grr_summary.csv", parse_dates=["month"])
    pipeline = pd.read_csv("data/renewal_pipeline.csv", parse_dates=["renewal_date"])
    seg_sum  = pd.read_csv("data/segment_health_summary.csv")
    country  = pd.read_csv("data/country_health_summary.csv")
    interv   = pd.read_csv("data/cs_intervention_list.csv")
    return scored, nrr_grr, pipeline, seg_sum, country, interv


# ── Panel builders ─────────────────────────────────────────────────────────────

def panel_kpi_strip(fig, gs_row, scored, nrr_grr, interv):
    """Top KPI strip: 5 headline metrics."""
    kpi_gs = gridspec.GridSpecFromSubplotSpec(1, 5, subplot_spec=gs_row, wspace=0.05)

    total_arr  = scored["arr"].sum()
    n_cust     = len(scored)
    at_risk_arr = scored["at_risk_arr"].sum()
    trailing_nrr = nrr_grr["nrr"].tail(3).mean()
    trailing_grr = nrr_grr["grr"].tail(3).mean()
    action_count = len(interv)

    kpis = [
        ("Total ARR",         f"€{total_arr/1_000_000:.2f}M", None),
        ("Customers",         f"{n_cust}",                    None),
        ("ARR at Risk (90d)", f"€{at_risk_arr:,.0f}",         COLORS["red"] if at_risk_arr > 50_000 else COLORS["amber"]),
        ("Trailing NRR",      f"{trailing_nrr:.1%}",          COLORS["green"] if trailing_nrr >= 1.0 else COLORS["amber"]),
        ("Priority Accounts", f"{action_count}",              COLORS["amber"]),
    ]

    for i, (label, value, vcolor) in enumerate(kpis):
        ax = fig.add_subplot(kpi_gs[i])
        ax.set_facecolor(COLORS["panel_bg"])
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")

        # Border
        for spine in ["top", "bottom", "left", "right"]:
            ax.spines[spine].set_visible(True)
            ax.spines[spine].set_color(COLORS["light_grey"])
            ax.spines[spine].set_linewidth(1.5)

        ax.text(0.5, 0.68, value,
                ha="center", va="center", fontsize=20, fontweight="bold",
                color=vcolor or COLORS["dark_grey"],
                transform=ax.transAxes)
        ax.text(0.5, 0.28, label,
                ha="center", va="center", fontsize=9, color=COLORS["grey"],
                transform=ax.transAxes)


def panel_health_donut(ax, scored):
    """Panel A: Customer health tier distribution (donut)."""
    tier_order = ["Green", "Amber", "Red"]
    tier_counts = scored["health_tier"].value_counts().reindex(tier_order, fill_value=0)
    tier_arr    = scored.groupby("health_tier")["arr"].sum().reindex(tier_order, fill_value=0)

    colors = [TIER_COLORS[t] for t in tier_order]
    wedges, _ = ax.pie(
        tier_counts,
        colors=colors,
        startangle=90,
        counterclock=False,
        wedgeprops={"width": 0.55, "edgecolor": "white", "linewidth": 2},
    )

    total = tier_counts.sum()
    ax.text(0, 0.06, str(total), ha="center", va="center",
            fontsize=22, fontweight="bold", color=COLORS["dark_grey"])
    ax.text(0, -0.22, "customers", ha="center", va="center",
            fontsize=9, color=COLORS["grey"])

    # Legend with counts + ARR
    legend_elements = [
        mpatches.Patch(
            facecolor=TIER_COLORS[t], label=f"{t}: {tier_counts[t]} ({tier_arr[t]/1000:.0f}K ARR)"
        ) for t in tier_order
    ]
    ax.legend(handles=legend_elements, loc="lower center", bbox_to_anchor=(0.5, -0.22),
              fontsize=8, frameon=False, ncol=1)
    ax.set_title("Customer Health Distribution", fontsize=10, fontweight="bold",
                 color=COLORS["text"], pad=10)


def panel_nrr_trend(ax, nrr_grr):
    """Panel B: NRR and GRR trend over 12 months."""
    df = nrr_grr.tail(11)  # last 11 months of transitions

    months = df["month"].dt.strftime("%b '%y")
    x = range(len(months))

    ax.plot(x, df["nrr"], color=COLORS["blue"], linewidth=2.5,
            marker="o", markersize=5, label="NRR", zorder=3)
    ax.plot(x, df["grr"], color=COLORS["grey"], linewidth=2,
            marker="s", markersize=4, linestyle="--", label="GRR", zorder=3)

    ax.axhline(y=1.0, color=COLORS["red"], linewidth=1, linestyle=":",
               alpha=0.7, label="100% baseline")

    ax.fill_between(x, df["nrr"], 1.0,
                    where=(df["nrr"] >= 1.0),
                    alpha=0.12, color=COLORS["green"], interpolate=True)
    ax.fill_between(x, df["nrr"], 1.0,
                    where=(df["nrr"] < 1.0),
                    alpha=0.15, color=COLORS["red"], interpolate=True)

    ax.set_xticks(list(x))
    ax.set_xticklabels(months, rotation=30, ha="right", fontsize=7.5)
    ax.yaxis.set_major_formatter(pct_fmt)
    ax.set_ylim(0.88, 1.12)
    ax.set_title("NRR / GRR Trend (12 months)", fontsize=10, fontweight="bold",
                 color=COLORS["text"])
    ax.legend(fontsize=8, frameon=False, loc="upper left")
    ax.set_facecolor(COLORS["panel_bg"])
    ax.grid(axis="y", color=COLORS["light_grey"], linewidth=0.8, zorder=0)
    ax.spines[["top", "right"]].set_visible(False)


def panel_segment_health(ax, seg_sum):
    """Panel C: Segment-level health breakdown — stacked bars."""
    seg_order = ["Enterprise", "Mid-Market", "SMB"]
    df = seg_sum.set_index("segment").reindex(seg_order)

    green_pct = df["green_count"] / df["customers"] * 100
    amber_pct = df["amber_count"] / df["customers"] * 100
    red_pct   = df["red_count"]   / df["customers"] * 100

    y = range(len(seg_order))
    bar_h = 0.5

    ax.barh(y, green_pct, height=bar_h, color=COLORS["green"], label="Green")
    ax.barh(y, amber_pct, height=bar_h, left=green_pct, color=COLORS["amber"], label="Amber")
    ax.barh(y, red_pct,   height=bar_h, left=green_pct + amber_pct, color=COLORS["red"], label="Red")

    for i, seg in enumerate(seg_order):
        arr = df.loc[seg, "total_arr"]
        risk_arr = df.loc[seg, "at_risk_arr"]
        ax.text(101, i, f"{arr/1000:.0f}K ARR",
                va="center", fontsize=8, color=COLORS["dark_grey"])
        if risk_arr > 0:
            ax.text(101, i - 0.22, f"  ⚠ €{risk_arr:,.0f} at risk",
                    va="center", fontsize=7, color=COLORS["red"])

    ax.set_yticks(list(y))
    ax.set_yticklabels(seg_order, fontsize=9)
    ax.set_xlim(0, 145)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x:.0f}%"))
    ax.set_title("Health Distribution by Segment", fontsize=10, fontweight="bold",
                 color=COLORS["text"])
    ax.legend(fontsize=8, frameon=False, loc="lower right")
    ax.set_facecolor(COLORS["panel_bg"])
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="x", color=COLORS["light_grey"], linewidth=0.8, zorder=0)


def panel_arr_at_risk_by_risk_level(ax, pipeline):
    """Panel D: ARR at risk by renewal risk tier and segment."""
    df = pipeline[pipeline["renewal_risk"].isin(["Critical", "High", "Medium"])].copy()

    pivot = df.pivot_table(
        index="segment", columns="renewal_risk", values="arr_at_risk", aggfunc="sum", fill_value=0
    )
    risk_cols = [c for c in ["Critical", "High", "Medium"] if c in pivot.columns]
    pivot = pivot[risk_cols]

    seg_order = ["Enterprise", "Mid-Market", "SMB"]
    pivot = pivot.reindex([s for s in seg_order if s in pivot.index])

    x = range(len(pivot))
    width = 0.25
    offsets = np.linspace(-(len(risk_cols)-1)*width/2, (len(risk_cols)-1)*width/2, len(risk_cols))

    for j, (col, offset) in enumerate(zip(risk_cols, offsets)):
        vals = pivot[col]
        bars = ax.bar([xi + offset for xi in x], vals,
                      width=width, color=RISK_COLORS[col], label=col, alpha=0.85)
        for bar, val in zip(bars, vals):
            if val > 1000:
                ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 300,
                        f"€{val:,.0f}", ha="center", va="bottom", fontsize=6.5,
                        color=COLORS["dark_grey"], rotation=45)

    ax.set_xticks(list(x))
    ax.set_xticklabels(pivot.index, fontsize=9)
    ax.yaxis.set_major_formatter(keur_fmt)
    ax.set_title("ARR at Risk: Renewal Window by Segment", fontsize=10, fontweight="bold",
                 color=COLORS["text"])
    ax.legend(fontsize=8, frameon=False, title="Risk Level", title_fontsize=8)
    ax.set_facecolor(COLORS["panel_bg"])
    ax.grid(axis="y", color=COLORS["light_grey"], linewidth=0.8, zorder=0)
    ax.spines[["top", "right"]].set_visible(False)


def panel_health_scatter(ax, scored):
    """Panel E: Health score vs ARR scatter — identifies high-value at-risk accounts."""
    df = scored.copy()
    tier_color_map = df["health_tier"].map(TIER_COLORS)

    scatter = ax.scatter(
        df["health_score"],
        df["arr"],
        c=tier_color_map,
        alpha=0.65,
        s=df["vehicle_count"] / df["vehicle_count"].max() * 120 + 15,
        edgecolors="white",
        linewidth=0.4,
        zorder=3,
    )

    # Label top-5 highest ARR at-risk accounts
    at_risk = df[df["churn_risk_flag"]].nlargest(5, "arr")
    for _, row in at_risk.iterrows():
        ax.annotate(
            f"{row['customer_id']}\n€{row['arr']:,.0f}",
            xy=(row["health_score"], row["arr"]),
            xytext=(8, 8), textcoords="offset points",
            fontsize=6.5, color=COLORS["red"],
            arrowprops={"arrowstyle": "->", "color": COLORS["red"], "lw": 0.8},
        )

    # Risk zone shading
    ax.axvspan(0, 40, alpha=0.05, color=COLORS["red"])
    ax.axvspan(40, 70, alpha=0.04, color=COLORS["amber"])

    ax.yaxis.set_major_formatter(keur_fmt)
    ax.set_xlabel("Health Score", fontsize=9, color=COLORS["text"])
    ax.set_ylabel("ARR", fontsize=9, color=COLORS["text"])
    ax.set_title("Health Score vs ARR (size = vehicle count)", fontsize=10,
                 fontweight="bold", color=COLORS["text"])
    ax.set_facecolor(COLORS["panel_bg"])
    ax.grid(color=COLORS["light_grey"], linewidth=0.6, zorder=0)
    ax.spines[["top", "right"]].set_visible(False)

    legend_elements = [
        mpatches.Patch(facecolor=COLORS["green"], label="Green"),
        mpatches.Patch(facecolor=COLORS["amber"], label="Amber"),
        mpatches.Patch(facecolor=COLORS["red"],   label="Red"),
    ]
    ax.legend(handles=legend_elements, fontsize=8, frameon=False)


def panel_intervention_table(ax, interv):
    """Panel F: Top 10 CS intervention priorities — table format."""
    ax.axis("off")

    top10 = interv.head(10)[[
        "priority_rank", "customer_id", "segment",
        "arr_at_risk", "health_score", "months_to_renewal",
        "primary_risk_signal"
    ]].copy()

    top10["arr_at_risk"] = top10["arr_at_risk"].apply(lambda x: f"€{x:,.0f}")
    top10["health_score"] = top10["health_score"].apply(lambda x: f"{x:.0f}")
    top10["months_to_renewal"] = top10["months_to_renewal"].apply(lambda x: f"{x}m")

    # Truncate signal text for table display
    top10["primary_risk_signal"] = top10["primary_risk_signal"].str[:45]

    col_labels = ["#", "Customer", "Seg.", "ARR Risk", "Health", "Renew", "Primary Signal"]
    col_widths = [0.04, 0.11, 0.07, 0.10, 0.07, 0.07, 0.54]

    table = ax.table(
        cellText=top10.values,
        colLabels=col_labels,
        cellLoc="left",
        loc="center",
        colWidths=col_widths,
    )

    table.auto_set_font_size(False)
    table.set_fontsize(7.5)
    table.scale(1, 1.6)

    # Style header
    for j in range(len(col_labels)):
        cell = table[0, j]
        cell.set_facecolor(COLORS["dark_blue"])
        cell.set_text_props(color="white", fontweight="bold", fontsize=7.5)

    # Alternating rows + red highlight for critical
    for i in range(len(top10)):
        risk = interv.iloc[i]["renewal_risk"]
        row_color = COLORS["light_grey"] if i % 2 == 0 else COLORS["panel_bg"]
        if risk == "Critical":
            row_color = "#FADBD8"
        for j in range(len(col_labels)):
            table[i+1, j].set_facecolor(row_color)

    ax.set_title("Top 10 CS Intervention Priorities — Next 90 Days",
                 fontsize=10, fontweight="bold", color=COLORS["text"],
                 pad=16, loc="left")


# ── Assemble dashboard ─────────────────────────────────────────────────────────

def build_dashboard():
    scored, nrr_grr, pipeline, seg_sum, country, interv = load_data()

    fig = plt.figure(figsize=(18, 14), facecolor=COLORS["bg"])

    # Master grid: [header strip] + [KPI strip] + [2×3 panels]
    outer_gs = gridspec.GridSpec(
        4, 1,
        figure=fig,
        height_ratios=[0.06, 0.10, 0.42, 0.42],
        hspace=0.35,
    )

    # ── Header ──────────────────────────────────────────────────────────────
    header_ax = fig.add_subplot(outer_gs[0])
    header_ax.set_facecolor(COLORS["dark_blue"])
    header_ax.axis("off")
    header_ax.text(0.015, 0.5,
                   "Fleet SaaS CX Operations Dashboard  |  Q4 2024 — As of 31 Dec 2024",
                   va="center", ha="left", fontsize=13, fontweight="bold",
                   color="white", transform=header_ax.transAxes)
    header_ax.text(0.985, 0.5,
                   "DACH Market · Post-Merger Portfolio · 250 Customers",
                   va="center", ha="right", fontsize=9.5, color=COLORS["light_blue"],
                   transform=header_ax.transAxes)

    # ── KPI strip ────────────────────────────────────────────────────────────
    panel_kpi_strip(fig, outer_gs[1], scored, nrr_grr, interv)

    # ── Main panels (2 rows × 3 cols) ───────────────────────────────────────
    top_gs = gridspec.GridSpecFromSubplotSpec(
        1, 3, subplot_spec=outer_gs[2], wspace=0.32, hspace=0.0
    )
    bot_gs = gridspec.GridSpecFromSubplotSpec(
        1, 3, subplot_spec=outer_gs[3], wspace=0.32, hspace=0.0
    )

    ax_A = fig.add_subplot(top_gs[0])
    ax_B = fig.add_subplot(top_gs[1])
    ax_C = fig.add_subplot(top_gs[2])
    ax_D = fig.add_subplot(bot_gs[0])
    ax_E = fig.add_subplot(bot_gs[1])
    ax_F = fig.add_subplot(bot_gs[2])

    for ax in [ax_A, ax_B, ax_C, ax_D, ax_E, ax_F]:
        ax.set_facecolor(COLORS["panel_bg"])

    panel_health_donut(ax_A, scored)
    panel_nrr_trend(ax_B, nrr_grr)
    panel_segment_health(ax_C, seg_sum)
    panel_arr_at_risk_by_risk_level(ax_D, pipeline)
    panel_health_scatter(ax_E, scored)
    panel_intervention_table(ax_F, interv)

    plt.savefig(
        "dashboards/cx_ops_executive_dashboard.png",
        dpi=150, bbox_inches="tight",
        facecolor=COLORS["bg"],
    )
    print("✓ Dashboard saved → dashboards/cx_ops_executive_dashboard.png")


if __name__ == "__main__":
    build_dashboard()
