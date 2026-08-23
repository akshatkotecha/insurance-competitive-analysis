"""
Insurance competitive-intelligence dashboard — Streamlit front end.

    streamlit run Python/dashboard.py

Four analysis tabs plus a fifth "Ask" tab embedding chatbotsqql's chat
widget. Every query goes through business.vw_* views in SQL Server
(INSURANCEDB on AKSHAT\\SQLEXPRESS). Connection pattern (pyodbc, thread-local
connection reuse) and CONN_STR both come from chatbot_core.py — the same
module chatbotsqql.py itself is built on — so this file never redefines
either.

Focal company: ABHI. Every view is framed as ABHI against its six
competitors (Care Health carries no premium data and is excluded from the
comparison views — it only shows up in the Data coverage expander).
"""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import chatbot_core as core
import chatbotsqql

# =====================================
# CONFIG
# =====================================

FOCAL_COMPANY = "ABHI"

AGE_BAND_ORDER = ["18-25", "26-35", "36-45", "46-55", "56-65", "66+"]

# categorical palette, fixed order — ABHI first since it's the focal
# company on every chart. Care Health has no premium/financial data in
# any of these views, so it isn't part of this comparison set.
COMPANY_COLORS = {
    "ABHI":          "#2a78d6",
    "Bajaj Allianz":  "#eb6834",
    "HDFC ERGO":      "#1baf7a",
    "ICICI Lombard":  "#eda100",
    "Niva Bupa":      "#e87ba4",
    "Star Health":    "#008300",
    "Tata AIG":       "#4a3aa7",
}

GOOD = "#0ca30c"
CRITICAL = "#d03b3b"
NEUTRAL = "#f0efec"


# =====================================
# DATA — same connection (chatbot_core.get_conn) as chatbotsqql.py,
# each query additionally cached here with st.cache_data per the brief.
# =====================================

@st.cache_data(ttl=600)
def load_abhi_vs_market():
    return pd.read_sql("SELECT * FROM business.vw_abhi_vs_market", core.get_conn())


@st.cache_data(ttl=600)
def load_premium():
    return pd.read_sql("SELECT * FROM business.vw_premium", core.get_conn())


@st.cache_data(ttl=600)
def load_head_to_head():
    return pd.read_sql("SELECT * FROM business.vw_head_to_head", core.get_conn())


@st.cache_data(ttl=600)
def load_metrics_long():
    return pd.read_sql("SELECT * FROM business.vw_metrics_long", core.get_conn())


@st.cache_data(ttl=600)
def load_peer_comparison():
    return pd.read_sql("SELECT * FROM business.vw_peer_comparison", core.get_conn())


@st.cache_data(ttl=600)
def load_data_quality():
    return pd.read_sql("SELECT * FROM business.vw_data_quality", core.get_conn())


@st.cache_data(ttl=600)
def load_metric_coverage():
    return pd.read_sql("SELECT * FROM business.vw_metric_coverage", core.get_conn())


# =====================================
# FORMATTING HELPERS
# =====================================

def fmt_cover(si):
    if pd.isna(si):
        return "—"
    return f"{si/10000000:g} Cr" if si >= 10000000 else f"{si/100000:g} L"


def fmt_rupees(v):
    if pd.isna(v):
        return "—"
    return f"Rs {v:,.0f}"


def si_label_order(df):
    """si_label is a display string, not a key — sort the labels actually
    present by their real sum_insured rather than alphabetically ('1 Cr'
    would otherwise sort before '10 L')."""
    return (df[["si_label", "sum_insured"]].drop_duplicates()
            .sort_values("sum_insured")["si_label"].tolist())


# =====================================
# UI
# =====================================

st.set_page_config(page_title="ABHI Competitive Intelligence", layout="wide")

with st.sidebar:
    st.title("ABHI Competitive Intelligence")
    st.caption("ABHI is the focal company throughout — every chart and table "
               "here reads as ABHI versus its six competitors.")

st.title("Health insurance — competitive intelligence")

tab_position, tab_peer, tab_trends, tab_pricing, tab_ask = st.tabs(
    ["Position", "Peer comparison", "Trends", "Pricing detail", "Ask"])

# ---------------------------------------------------------------
# TAB 1 — POSITION
# ---------------------------------------------------------------
with tab_position:
    pos = load_abhi_vs_market()
    si_order = si_label_order(pos)

    # "market" in this view can mean anywhere from 1 to 6 competitors —
    # the entire 2 Cr column is priced against exactly one rival
    # (market_min == market_max there), and 75 L against only 3-4. A
    # 1-competitor "average" isn't a market average, so headline KPIs
    # are computed on the reliable subset and the full-sample numbers
    # are disclosed alongside rather than silently blended in.
    RELIABLE_MIN_COMPETITORS = 5
    reliable = pos[pos["competitor_count"] >= RELIABLE_MIN_COMPETITORS]
    n_thin = len(pos) - len(reliable)

    c1, c2, c3, c4 = st.columns(4)

    reliable_index = reliable["price_index"].mean()
    all_index = pos["price_index"].mean()
    c1.metric("Overall price index", f"{reliable_index:.1f}",
              help=f"Mean of price_index restricted to segments priced against at least "
                   f"{RELIABLE_MIN_COMPETITORS} competitors ({len(reliable)} of {len(pos)} "
                   f"segments). Across all {len(pos)} segments — including the five 2 Cr cells "
                   f"priced against a single rival — the mean is {all_index:.1f}; that number "
                   f"looks 'cheaper' only because a 1-competitor comparison isn't a market read.")
    c1.caption(f"{n_thin} thin segments excluded — see heatmap")

    modal_position = reliable["position"].mode().iat[0]
    modal_count = int((reliable["position"] == modal_position).sum())
    with c2:
        st.caption("Most common position")
        st.markdown(f"### {modal_position}")
        st.caption(f"{modal_count} of {len(reliable)} reliable segments")

    cheapest_row = pos.loc[pos["abhi_premium"].idxmin()]
    c3.metric("ABHI's cheapest slab", fmt_rupees(cheapest_row["abhi_premium"]))
    c3.caption(f"{cheapest_row['age_band']} · {cheapest_row['si_label']} — "
               f"market min {fmt_rupees(cheapest_row['market_min'])} "
               f"(n={int(cheapest_row['competitor_count'])} competitors)")

    n_cheapest_reliable = int(reliable["is_cheapest"].sum())
    n_cheapest_all = int(pos["is_cheapest"].sum())
    c4.metric("Segments where ABHI is cheapest", f"{n_cheapest_reliable} / {len(reliable)}")
    c4.caption(f"{n_cheapest_all} / {len(pos)} if thin segments are included")

    st.caption("⚠️ ABHI's within-product age curve is unreliable — its source "
               "rate chart interleaves two rate tables. Treat single-age "
               "premium reads with caution; segment-level comparisons here "
               "are still valid. (See Data coverage below.)")

    st.subheader("Price index by age band × cover")
    st.caption("Price index = ABHI premium ÷ market average × 100. Green below 100, red above — "
               f"centred exactly on market. Cells washed out and marked **(n=…)** are priced "
               f"against fewer than {RELIABLE_MIN_COMPETITORS} competitors — most visibly the "
               "entire **2 Cr** column, which is a single head-to-head against one rival, not a "
               "market comparison; **75 L** is thin too, at 3-4 competitors.")

    grid = pos.pivot(index="age_band", columns="si_label", values="price_index")
    grid = grid.reindex(index=AGE_BAND_ORDER, columns=si_order)
    n_grid = pos.pivot(index="age_band", columns="si_label", values="competitor_count")
    n_grid = n_grid.reindex(index=AGE_BAND_ORDER, columns=si_order)

    def _cell_label(v, n):
        if pd.isna(v):
            return ""
        label = f"{v:.0f}"
        if pd.notna(n) and n < RELIABLE_MIN_COMPETITORS:
            label += f" (n={int(n)})"
        return label

    z_vals, n_vals = grid.values, n_grid.values
    cell_text = [[_cell_label(z_vals[i][j], n_vals[i][j]) for j in range(z_vals.shape[1])]
                 for i in range(z_vals.shape[0])]

    thin_mask = n_grid < RELIABLE_MIN_COMPETITORS
    mute_z = thin_mask.where(thin_mask).astype(float)  # 1.0 where thin, NaN elsewhere

    heat = go.Figure(go.Heatmap(
        z=grid.values, x=grid.columns, y=grid.index,
        colorscale=[[0.0, GOOD], [0.5, NEUTRAL], [1.0, CRITICAL]],
        zmid=100,
        text=cell_text, texttemplate="%{text}",
        textfont=dict(size=11),
        customdata=n_grid.values,
        hovertemplate=("Age %{y}, cover %{x}<br>Price index: %{z:.1f}<br>"
                        "Competitors compared: %{customdata:.0f}<extra></extra>"),
        colorbar=dict(title="Price<br>index"),
    ))
    heat.add_trace(go.Heatmap(
        z=mute_z.values, x=grid.columns, y=grid.index,
        colorscale=[[0, "#ffffff"], [1, "#ffffff"]], zmin=0, zmax=1,
        opacity=0.55, showscale=False, hoverinfo="skip",
    ))
    heat.update_layout(height=420, xaxis_title="Sum insured", yaxis_title="Age band",
                        margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(heat, use_container_width=True)

    st.subheader("ABHI vs. market average premium")
    slab = st.selectbox("Cover amount", si_order,
                         index=si_order.index("10 L") if "10 L" in si_order else 0)
    sub = pos[pos["si_label"] == slab].copy()
    sub["age_band"] = pd.Categorical(sub["age_band"], categories=AGE_BAND_ORDER, ordered=True)
    sub = sub.sort_values("age_band")

    bar = go.Figure()
    bar.add_bar(name="ABHI", x=sub["age_band"], y=sub["abhi_premium"],
                marker_color=COMPANY_COLORS[FOCAL_COMPANY])
    bar.add_bar(name="Market average", x=sub["age_band"], y=sub["market_avg"],
                marker_color="#8a8a8a")
    bar.update_layout(barmode="group", height=380, yaxis_title="Premium (Rs)",
                       xaxis_title="Age band", margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(bar, use_container_width=True)

    with st.expander("Data coverage"):
        dq = load_data_quality()
        st.dataframe(
            dq[["company_name", "product_name", "premium_rows", "slabs", "tiers", "caveat"]]
            .rename(columns={"company_name": "Insurer", "product_name": "Product",
                              "premium_rows": "Premium rows", "slabs": "Slabs",
                              "tiers": "Tiers", "caveat": "Caveat"}),
            hide_index=True, use_container_width=True)

# ---------------------------------------------------------------
# TAB 2 — PEER COMPARISON
# ---------------------------------------------------------------
with tab_peer:
    peer = load_peer_comparison().sort_values("gwp", ascending=False, na_position="last")

    display_cols = {
        "company_name": "Insurer", "financial_year": "FY",
        "gwp": "GWP (Rs Cr)", "gdpi": "GDPI (Rs Cr)", "net_worth": "Net worth (Rs Cr)",
        "aum": "AUM (Rs Cr)", "market_share": "Market share (%)", "roe": "ROE (%)",
        "roa": "ROA (%)", "solvency_ratio": "Solvency (x)",
        "combined_ratio": "Combined ratio (%)", "icr": "ICR (%)",
        "gwp_to_net_worth": "GWP / net worth (x)",
    }
    table = peer[list(display_cols)].rename(columns=display_cols).reset_index(drop=True)
    numeric_cols = [c for c in table.columns if c not in ("Insurer", "FY")]
    peer_indexed = peer.reset_index(drop=True)
    for c in numeric_cols:
        table[c] = pd.to_numeric(table[c], errors="coerce").map(
            lambda v: "—" if pd.isna(v) else f"{v:,.2f}")

    def highlight_abhi(row):
        is_abhi = peer_indexed.loc[row.name, "company_name"] == FOCAL_COMPANY
        style = f"background-color: {COMPANY_COLORS[FOCAL_COMPANY]}22; font-weight: 600;" if is_abhi else ""
        return [style] * len(row)

    st.subheader("Peer comparison — FY25")
    st.caption(f"Sorted by GWP descending — {FOCAL_COMPANY} highlighted.")
    st.dataframe(table.style.apply(highlight_abhi, axis=1), hide_index=True, use_container_width=True)

    st.subheader("Market share")
    ms = peer.dropna(subset=["market_share"]).sort_values("market_share", ascending=False)
    if ms.empty:
        st.info("No insurer in this view carries a market_share value.")
    else:
        fig = px.bar(ms, x="company_name", y="market_share", color="company_name",
                     color_discrete_map=COMPANY_COLORS,
                     labels={"company_name": "Insurer", "market_share": "Market share (%)"})
        fig.update_layout(showlegend=False, height=380, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)
        st.caption(f"Only {len(ms)} of {len(peer)} insurers carry a market_share figure in this view.")

# ---------------------------------------------------------------
# TAB 3 — TRENDS
# ---------------------------------------------------------------
with tab_trends:
    metrics = load_metrics_long()
    metric_names = sorted(metrics["metric_name"].unique())
    default_ix = metric_names.index("GWP") if "GWP" in metric_names else 0

    col_a, col_b = st.columns([3, 1])
    metric = col_a.selectbox("Metric", metric_names, index=default_ix)
    index_to_first_year = col_b.toggle("Index to first year", value=False,
                                        help="Rescale each company's series to 100 at its "
                                             "first available year — useful since GWP is an "
                                             "order of magnitude larger than ratio metrics.")

    st.caption("Only GWP and ROE hold five years across most insurers; combined ratio has "
               "no year coverage at all and market share only one year for a handful of "
               "insurers — see vw_metric_coverage.")

    mdf = metrics[metrics["metric_name"] == metric].sort_values("fy_number").copy()
    year_order = (mdf[["financial_year", "fy_number"]]
                  .drop_duplicates().sort_values("fy_number")["financial_year"].tolist())
    unit = mdf["metric_unit"].mode().iat[0] if not mdf.empty else ""

    if mdf.empty:
        st.info("No data held for this metric.")
    else:
        y_col, y_title = "metric_value", f"{metric} ({unit})" if unit else metric
        if index_to_first_year:
            mdf = mdf.sort_values(["company_name", "fy_number"])
            first_vals = mdf.groupby("company_name")["metric_value"].transform("first")
            mdf["indexed_value"] = mdf["metric_value"] / first_vals * 100
            y_col, y_title = "indexed_value", f"{metric}, indexed to first year (=100)"

        fig = px.line(
            mdf, x="financial_year", y=y_col, color="company_name", markers=True,
            category_orders={"financial_year": year_order, "company_name": list(COMPANY_COLORS)},
            color_discrete_map=COMPANY_COLORS,
            labels={"financial_year": "Financial year", y_col: y_title, "company_name": "Insurer"},
        )
        fig.update_traces(line=dict(width=2), marker=dict(size=7))
        fig.update_traces(selector=dict(name=FOCAL_COMPANY), line=dict(width=4))
        fig.update_layout(height=460, hovermode="x unified", margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------
# TAB 4 — PRICING DETAIL
# ---------------------------------------------------------------
with tab_pricing:
    premium = load_premium()
    base = premium[
        (premium["city_tier"] == "Tier 1")
        & (premium["adults"] == 1)
        & (premium["children"] == 0)
    ]

    st.subheader("Premium per lakh vs. sum insured")
    st.caption("Tier 1, 1 adult, 0 children.")

    age_bands = [b for b in AGE_BAND_ORDER if b in base["age_band"].unique()]
    selected_bands = st.multiselect("Age band", age_bands, default=age_bands)
    filtered = base[base["age_band"].isin(selected_bands)] if selected_bands else base.iloc[0:0]

    if filtered.empty:
        st.info("No rows for this filter — pick at least one age band.")
    else:
        fig = px.scatter(
            filtered, x="sum_insured", y="premium_per_lakh", color="company_name",
            color_discrete_map=COMPANY_COLORS,
            category_orders={"company_name": list(COMPANY_COLORS)},
            opacity=0.55, log_x=True,
            hover_data={"age": True, "age_band": True, "premium_amount": True,
                        "sum_insured": ":,", "premium_per_lakh": ":.0f", "company_name": False},
            labels={"sum_insured": "Sum insured (Rs, log scale)",
                    "premium_per_lakh": "Premium per lakh of cover (Rs)",
                    "company_name": "Insurer"},
        )
        fig.update_traces(marker=dict(size=7, line=dict(width=1, color="white")))
        fig.update_layout(height=480, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, use_container_width=True)

    st.divider()
    st.subheader("Head-to-head")
    h2h = load_head_to_head()
    if h2h.empty:
        st.info("vw_head_to_head returned no rows.")
    else:
        rivals = sorted(h2h["rival"].unique())
        rival = st.selectbox("Rival", rivals)
        h2h_sub = h2h[h2h["rival"] == rival].copy()
        h2h_sub["age_band"] = pd.Categorical(h2h_sub["age_band"], categories=AGE_BAND_ORDER, ordered=True)
        si_order_h2h = si_label_order(h2h_sub)
        h2h_sub["si_label"] = pd.Categorical(h2h_sub["si_label"], categories=si_order_h2h, ordered=True)
        h2h_sub = h2h_sub.sort_values(["age_band", "si_label"])

        display = h2h_sub[["age_band", "si_label", "abhi_premium", "rival_premium",
                            "gap_rupees", "index_vs_rival", "winner"]].rename(columns={
            "age_band": "Age band", "si_label": "Cover", "abhi_premium": "ABHI premium",
            "rival_premium": f"{rival} premium", "gap_rupees": "Gap (Rs)",
            "index_vs_rival": "Index vs rival", "winner": "Winner",
        })

        def color_gap(v):
            if pd.isna(v):
                return ""
            color = GOOD if v < 0 else CRITICAL
            return f"color: {color}; font-weight: 600;"

        styled = (display.style
                  .format({"ABHI premium": "Rs {:,.0f}", f"{rival} premium": "Rs {:,.0f}",
                           "Gap (Rs)": "Rs {:+,.0f}", "Index vs rival": "{:.1f}"})
                  .map(color_gap, subset=["Gap (Rs)"]))
        st.dataframe(styled, hide_index=True, use_container_width=True)
        st.caption("Negative gap (green) = ABHI cheaper than this rival at that segment.")

# ---------------------------------------------------------------
# TAB 5 — ASK (embedded chatbot)
# ---------------------------------------------------------------
with tab_ask:
    st.subheader("Ask the database")
    st.caption("Same SQL-only assistant as chatbotsqql.py — every answer is a direct lookup, "
               "nothing is generated.")
    chatbotsqql.render_chat()
