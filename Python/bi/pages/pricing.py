"""Page 2 — Price position."""

from __future__ import annotations

import dash
import dash_bootstrap_components as dbc
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, callback, html

from bi import components as ui
from bi import data, insights, theme

dash.register_page(__name__, path="/pricing", name="Price position", order=1)

ALL = "All"


def _options(values, label_fn=str):
    return [{"label": ALL, "value": ALL}] + [
        {"label": label_fn(v), "value": v} for v in values]


def _controls():
    avm = data.get("vw_abhi_vs_market")
    prem = data.get("vw_premium")

    slabs = sorted(avm["sum_insured"].dropna().unique())
    bands = [b for b in data.AGE_BAND_ORDER if b in set(avm["age_band"].dropna())]
    tiers = sorted(prem["city_tier"].dropna().unique())
    comps = sorted(prem["composition"].dropna().unique())

    def col(label, cid, opts, value):
        return dbc.Col([
            html.Label(label, className="bi-muted",
                       style={"fontSize": "11px", "fontWeight": 700,
                              "textTransform": "uppercase",
                              "letterSpacing": ".04em"}),
            dbc.Select(id=cid, options=opts, value=value, size="sm",
                       style={"fontSize": "13px"}),
        ], md=3)

    return dbc.Card(dbc.CardBody(dbc.Row([
        col("Cover amount", "pp-cover", _options(slabs, data.cover),
            1000000.0 if 1000000.0 in slabs else slabs[0]),
        col("Age band", "pp-band", _options(bands), ALL),
        col("City tier", "pp-tier", _options(tiers),
            "Tier 1" if "Tier 1" in tiers else ALL),
        col("Composition", "pp-comp", _options(comps),
            "1A+0C" if "1A+0C" in comps else ALL),
    ], className="g-3")), className=f"mb-4 {ui.CARD}")


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------

def bar_vs_market(avm: pd.DataFrame, mode: str) -> go.Figure:
    """ABHI against the competitor mean per age band, with the competitor
    min-max spread as error bars."""
    if avm.empty:
        return theme.empty_figure(mode=mode)

    g = (avm.groupby("age_band", observed=True)
         .agg(abhi=("abhi_premium", "mean"), mkt=("market_avg", "mean"),
              lo=("market_min", "mean"), hi=("market_max", "mean"))
         .reset_index().dropna(subset=["abhi"]))
    if g.empty:
        return theme.empty_figure(mode=mode)

    order = [b for b in data.AGE_BAND_ORDER if b in set(g["age_band"])]
    g["age_band"] = pd.Categorical(g["age_band"], categories=order, ordered=True)
    g = g.sort_values("age_band")
    x = g["age_band"].astype(str)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=x, y=g["abhi"], name="ABHI",
        marker=dict(color=theme.focal_colour(mode), line=dict(width=0)),
        hovertemplate="ABHI · %{x}<br>Rs %{y:,.0f}<extra></extra>"))
    fig.add_trace(go.Bar(
        x=x, y=g["mkt"], name="Market average",
        marker=dict(color=theme.MUTED[mode], line=dict(width=0)),
        error_y=dict(type="data", symmetric=False,
                     array=(g["hi"] - g["mkt"]).clip(lower=0),
                     arrayminus=(g["mkt"] - g["lo"]).clip(lower=0),
                     color=theme.token("ink-secondary", mode),
                     thickness=1.2, width=5),
        hovertemplate="Market · %{x}<br>avg Rs %{y:,.0f}<extra></extra>"))

    fig.update_layout(barmode="group", bargap=0.28, bargroupgap=0.08,
                      height=360, yaxis_title="Premium (Rs)",
                      margin=dict(l=70, r=20, t=40, b=45))
    return theme.apply(fig, mode)


def line_by_age(prem: pd.DataFrame, cover_value, mode: str) -> go.Figure:
    """Premium against age for every insurer at one cover level."""
    if prem.empty:
        return theme.empty_figure("No premium rows for this selection", mode)

    g = (prem.groupby(["company_name", "age"], observed=True)["premium_amount"]
         .mean().reset_index())
    if g.empty:
        return theme.empty_figure(mode=mode)

    fig = go.Figure()
    # rivals first so ABHI draws on top of them
    for company in [c for c in theme.COMPANY_ORDER
                    if c in set(g["company_name"]) and c != data.FOCAL]:
        sub = g[g["company_name"] == company].sort_values("age")
        fig.add_trace(go.Scatter(
            x=sub["age"], y=sub["premium_amount"], name=company, mode="lines",
            line=dict(color=theme.colour_for(company, mode), width=1.8),
            hovertemplate=f"{company}<br>age %{{x}} · Rs %{{y:,.0f}}"
                          "<extra></extra>"))

    if data.FOCAL in set(g["company_name"]):
        sub = g[g["company_name"] == data.FOCAL].sort_values("age")
        fig.add_trace(go.Scatter(
            x=sub["age"], y=sub["premium_amount"], name=data.FOCAL, mode="lines",
            line=dict(color=theme.focal_colour(mode), width=3.5),
            hovertemplate="ABHI<br>age %{x} · Rs %{y:,.0f}<extra></extra>"))

    title = (f"at {data.cover(cover_value)} cover" if cover_value != ALL
             else "all covers pooled")
    fig.update_layout(height=360, xaxis_title="Age", yaxis_title="Premium (Rs)",
                      title=dict(text=title,
                                 font=dict(size=12,
                                           color=theme.token("ink-muted", mode))),
                      margin=dict(l=70, r=20, t=54, b=45))
    return theme.apply(fig, mode)


def _gap_style(mode: str):
    return [
        {"if": {"filter_query": "{gap_rupees} < 0", "column_id": "gap_rupees"},
         "color": theme.severity("opportunity", mode)["colour"],
         "fontWeight": "600"},
        {"if": {"filter_query": "{gap_rupees} > 0", "column_id": "gap_rupees"},
         "color": theme.severity("risk", mode)["colour"], "fontWeight": "600"},
        {"if": {"filter_query":
                f"{{competitor_count}} < {insights.MIN_COMPETITORS}"},
         "backgroundColor": theme.token("surface-sunk", mode),
         "color": theme.token("ink-muted", mode), "fontStyle": "italic"},
    ]


# ---------------------------------------------------------------------------

def layout(**_):
    return html.Div([
        ui.page_header("Price position",
                       "Where ABHI sits against the competitor mean, "
                       "segment by segment"),
        _controls(),
        html.Div(id="pp-insights"),
        dbc.Row([
            dbc.Col(ui.section(
                "ABHI vs market average by age band",
                ui.graph(theme.empty_figure(), "pp-bar", height=360),
                note="Error bars span the competitor min-max range."), md=6),
            dbc.Col(ui.section(
                "Premium by age, every insurer",
                ui.graph(theme.empty_figure(), "pp-line", height=360),
                note="ABHI emphasised. A line that falls off a cliff is "
                     "extraction damage rather than pricing — see Data "
                     "quality."), md=6),
        ], className="g-3"),
        ui.section("Segment detail", html.Div(id="pp-table"),
                   note="Green = ABHI cheaper than the competitor mean. "
                        "Greyed rows are thin comparisons."),
    ])


@callback(
    Output("pp-insights", "children"),
    Output("pp-bar", "figure"),
    Output("pp-line", "figure"),
    Output("pp-table", "children"),
    Input("pp-cover", "value"),
    Input("pp-band", "value"),
    Input("pp-tier", "value"),
    Input("pp-comp", "value"),
    Input("theme-store", "data"),
)
def update(cover_value, band, tier, comp, mode):
    """Everything here runs against the in-memory store; no query is issued."""
    mode = theme.normalise(mode)
    avm = data.get("vw_abhi_vs_market")
    prem = data.get("vw_premium")

    if cover_value not in (None, ALL):
        cover_value = float(cover_value)
        avm = avm[avm["sum_insured"] == cover_value]
        prem = prem[prem["sum_insured"] == cover_value]
    if band not in (None, ALL):
        avm = avm[avm["age_band"].astype(str) == band]
        prem = prem[prem["age_band"].astype(str) == band]
    if tier not in (None, ALL):
        prem = prem[prem["city_tier"] == tier]
    if comp not in (None, ALL):
        prem = prem[prem["composition"] == comp]

    found = insights.price_position_by_age() + insights.widest_gaps()
    cards = dbc.Row([dbc.Col(ui.insight_card(i, f"pp-{n}", mode), md=6,
                             className="mb-3")
                     for n, i in enumerate(found)], className="g-3 mb-2")

    cols = ["age_band", "si_label", "abhi_premium", "market_avg", "market_min",
            "market_max", "competitor_count", "gap_rupees", "price_index",
            "position"]
    # sort on sum_insured before dropping it, so cover slabs stay in value order
    tbl = avm.sort_values(["age_band", "sum_insured"])[cols] if not avm.empty else avm
    table = ui.table(tbl, "pp-detail", page_size=12, highlight_focal=False,
                     conditional=_gap_style(mode), mode=mode)

    return (cards, bar_vs_market(avm, mode),
            line_by_age(prem, cover_value, mode), table)
