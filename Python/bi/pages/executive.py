"""Page 1 — Executive summary."""

from __future__ import annotations

import dash
import dash_bootstrap_components as dbc
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, callback, html

from bi import components as ui
from bi import data, insights, theme

dash.register_page(__name__, path="/", name="Executive summary", order=0)


# ---------------------------------------------------------------------------
# KPI row
# ---------------------------------------------------------------------------

def _kpis(mode: str) -> dbc.Row:
    avm = data.get("vw_abhi_vs_market")
    prem = data.get("vw_premium")
    sc = data.get("vw_abhi_scorecard")
    fg = data.get("vw_feature_gaps")

    reliable = avm[avm["competitor_count"] >= insights.MIN_COMPETITORS]
    idx = reliable["price_index"].mean() if not reliable.empty else np.nan
    thin = int((avm["competitor_count"] < insights.MIN_COMPETITORS).sum())
    cheapest = int(avm["is_cheapest"].sum()) if "is_cheapest" in avm else 0

    gwp = sc[sc["metric_name"] == "GWP"]
    if not gwp.empty:
        g = gwp.iloc[0]
        # units live in the KPI label, so the figure itself stays on one line
        gwp_value = data.inr(g["abhi_value"], prefix="")
        gwp_sub = (f"rank {int(g['rank_position'])} of {int(g['peer_count'])} · "
                   f"peer avg {data.num(g['peer_avg'], 0)}")
    else:
        gwp_value, gwp_sub = "—", "not in scorecard"

    abhi_slabs = prem.loc[prem["company_name"] == data.FOCAL, "sum_insured"].dropna()
    entry_abhi = abhi_slabs.min() if not abhi_slabs.empty else np.nan
    entry_mkt = prem["sum_insured"].min()
    n_at_entry = prem.loc[prem["sum_insured"] == entry_mkt, "company_name"].nunique()

    gaps = fg[(fg["abhi_has"] == 0) | fg["gap_status"].str.contains("Gap", na=False)]

    return dbc.Row([
        dbc.Col(ui.kpi("Overall price index", data.num(idx, 1),
                       f"reliable segments only (n≥{insights.MIN_COMPETITORS}) · "
                       f"under 100 = cheaper than market",
                       tone="good" if idx < 100 else "bad", mode=mode), md=2),
        dbc.Col(ui.kpi("ABHI cheapest", f"{cheapest} of {len(avm)}",
                       "segments where ABHI is the lowest price",
                       mode=mode), md=2),
        dbc.Col(ui.kpi("ABHI GWP FY25 (Rs Cr)", gwp_value, gwp_sub,
                       tone="bad", mode=mode), md=2),
        dbc.Col(ui.kpi("Entry slab", data.cover(entry_abhi),
                       f"market entry {data.cover(entry_mkt)} · "
                       f"{n_at_entry} insurers sell it",
                       tone="bad" if entry_abhi > entry_mkt else "good",
                       mode=mode), md=2),
        dbc.Col(ui.kpi("Feature gaps", str(len(gaps)),
                       f"of {len(fg)} benefits compared",
                       tone="bad" if len(gaps) else "good", mode=mode), md=2),
        dbc.Col(ui.kpi("Unreliable segments", str(thin),
                       f"fewer than {insights.MIN_COMPETITORS} competitors",
                       tone="bad" if thin else "good", mode=mode), md=2),
    ], className="g-3 mb-4")


# ---------------------------------------------------------------------------
# Price-index heatmap
# ---------------------------------------------------------------------------

def price_heatmap(avm: pd.DataFrame, mode: str) -> go.Figure:
    """Diverging on 100. Segments compared against fewer than four competitors
    are painted a flat grey and labelled with their competitor count, so a thin
    comparison can never read as a strong result."""
    if avm.empty:
        return theme.empty_figure(mode=mode)

    rows = [b for b in data.AGE_BAND_ORDER if b in set(avm["age_band"].dropna())]
    cols = data.si_order(avm)

    grid = avm.pivot_table(index="age_band", columns="si_label",
                           values="price_index", aggfunc="first", observed=True)
    counts = avm.pivot_table(index="age_band", columns="si_label",
                             values="competitor_count", aggfunc="first",
                             observed=True)
    grid = grid.reindex(index=rows, columns=cols)
    counts = counts.reindex(index=rows, columns=cols)

    reliable_mask = counts >= insights.MIN_COMPETITORS
    z_main = grid.where(reliable_mask)
    z_thin = grid.where(~reliable_mask & grid.notna())

    spread = (float(np.nanmax(np.abs(grid.values - 100.0)))
              if grid.notna().any().any() else 20.0)
    spread = max(spread, 10.0)

    fig = go.Figure()
    fig.add_trace(go.Heatmap(
        z=z_thin.notna().astype(float).where(z_thin.notna()).values,
        x=cols, y=rows, showscale=False, hoverinfo="skip",
        colorscale=[[0, theme.unreliable(mode)], [1, theme.unreliable(mode)]],
        xgap=2, ygap=2))

    fig.add_trace(go.Heatmap(
        z=z_main.values, x=cols, y=rows,
        colorscale=theme.price_scale(mode), zmid=100,
        zmin=100 - spread, zmax=100 + spread, xgap=2, ygap=2,
        colorbar=dict(title=dict(text="Index", side="right"), thickness=12,
                      len=0.75, outlinewidth=0, tickfont=dict(size=10)),
        hovertemplate="%{y} · %{x}<br>Price index %{z:.1f}<extra></extra>"))

    ann = []
    for r in rows:
        for c in cols:
            v = grid.loc[r, c]
            if pd.isna(v):
                continue
            n = counts.loc[r, c]
            thin = pd.notna(n) and n < insights.MIN_COMPETITORS
            txt = f"{v:.0f}" + (f"<br>(n={int(n)})" if thin else "")
            if thin:
                colour = theme.token("ink-secondary", mode)
            else:
                strong = abs(v - 100) > spread * 0.55
                colour = "#ffffff" if strong else theme.token("ink", mode)
            ann.append(dict(x=c, y=r, text=txt, showarrow=False,
                            font=dict(size=10.5, color=colour)))

    fig.update_layout(
        annotations=ann, height=330, margin=dict(l=70, r=20, t=10, b=40),
        xaxis=dict(side="top", showgrid=False, ticks="",
                   tickfont=dict(size=11, color=theme.token("ink-secondary", mode))),
        yaxis=dict(autorange="reversed", showgrid=False, ticks="",
                   tickfont=dict(size=11, color=theme.token("ink-secondary", mode))))
    return theme.apply(fig, mode)


# ---------------------------------------------------------------------------

def layout(**_):
    return html.Div(id="exec-body")


@callback(Output("exec-body", "children"), Input("theme-store", "data"))
def render(mode):
    mode = theme.normalise(mode)
    avm = data.get("vw_abhi_vs_market")
    dq = data.get("vw_data_quality")

    top3 = insights.highest_severity(insights.all_insights(), 3)

    coverage = dq[["company_name", "product_name", "premium_rows",
                   "slabs", "tiers", "caveat"]].sort_values(
        "premium_rows", ascending=False)
    flagged = coverage[coverage["caveat"].fillna("OK").str.upper() != "OK"]

    return html.Div([
        ui.page_header(
            "Executive summary",
            f"ABHI against seven insurers · {data.BASIS} · financials FY25"),

        _kpis(mode),

        ui.section("Highest-severity findings",
                   ui.insight_row(top3, "exec", mode=mode),
                   note="Risks first. Every card opens onto the rows behind it."),

        ui.section("Price index by age band and cover",
                   ui.graph(price_heatmap(avm, mode), "exec-heatmap", height=330),
                   note="100 = market average. Grey cells compare against fewer "
                        f"than {insights.MIN_COMPETITORS} competitors and are "
                        "not comparable."),

        ui.section("Data coverage",
                   ui.table(coverage, "exec-coverage", page_size=8,
                            wrap_columns=["caveat"], mode=mode),
                   note=f"{len(flagged)} of {len(coverage)} product rows carry a "
                        "caveat. The caveat column is the reason to distrust a "
                        "number, not a footnote."),
    ])
