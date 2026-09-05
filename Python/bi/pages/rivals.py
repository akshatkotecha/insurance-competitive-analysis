"""Page 3 — Competitor deep dive."""

from __future__ import annotations

import dash
import dash_bootstrap_components as dbc
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, callback, html

from bi import components as ui
from bi import data, insights, theme

dash.register_page(__name__, path="/rivals", name="Competitor deep dive", order=2)


def _selector():
    h2h = data.get("vw_head_to_head")
    rivals = sorted(h2h["rival"].dropna().unique().tolist())
    default = ("ICICI Lombard" if "ICICI Lombard" in rivals
               else (rivals[0] if rivals else None))
    return dbc.Card(dbc.CardBody(dbc.Row([
        dbc.Col([
            html.Label("Rival", className="bi-muted",
                       style={"fontSize": "11px", "fontWeight": 700,
                              "textTransform": "uppercase",
                              "letterSpacing": ".04em"}),
            dbc.Select(id="rv-rival",
                       options=[{"label": r, "value": r} for r in rivals],
                       value=default, size="sm", style={"fontSize": "13px"}),
        ], md=4),
        dbc.Col(html.Div(
            "Head-to-head compares ABHI against one rival on the segments both "
            "of them price. A rival that sells fewer slabs is compared on fewer "
            "segments — the counts differ by design.",
            className="bi-secondary",
            style={"fontSize": "12px", "paddingTop": "18px"}), md=8),
    ], className="g-3")), className=f"mb-4 {ui.CARD}")


# ---------------------------------------------------------------------------

def h2h_heatmap(sub: pd.DataFrame, rival: str, mode: str) -> go.Figure:
    if sub.empty:
        return theme.empty_figure(f"No shared segments with {rival}", mode)

    rows = [b for b in data.AGE_BAND_ORDER if b in set(sub["age_band"].dropna())]
    cols = data.si_order(sub)
    grid = (sub.pivot_table(index="age_band", columns="si_label",
                            values="index_vs_rival", aggfunc="first",
                            observed=True)
            .reindex(index=rows, columns=cols))

    vals = grid.values.astype(float)
    finite = vals[np.isfinite(vals)]
    if finite.size == 0:
        return theme.empty_figure(mode=mode)

    # Colour range clamped to the 90th percentile of the deviation from 100.
    # A handful of mis-parsed rival rows reach an index of 2,600 (see the
    # premium-outlier finding); unclamped they flatten every real cell to the
    # midpoint. The clamp touches colour only — the printed number and the
    # hover both show the true value.
    dev = np.abs(finite - 100.0)
    spread = max(float(np.percentile(dev, 90)) if dev.size else 20.0, 10.0)
    clamped = bool((dev > spread).any())

    fig = go.Figure(go.Heatmap(
        z=vals, x=cols, y=rows, colorscale=theme.price_scale(mode), zmid=100,
        zmin=100 - spread, zmax=100 + spread, xgap=2, ygap=2,
        colorbar=dict(title=dict(text="Index", side="right"), thickness=12,
                      len=0.75, outlinewidth=0, tickfont=dict(size=10)),
        hovertemplate=("%{y} · %{x}<br>ABHI vs " + rival +
                       ": index %{z:.1f}<extra></extra>")))

    ann = []
    for r in rows:
        for c in cols:
            v = grid.loc[r, c]
            if pd.isna(v):
                continue
            strong = abs(v - 100) > spread * 0.55
            ann.append(dict(x=c, y=r, text=f"{v:.0f}", showarrow=False,
                            font=dict(size=10.5,
                                      color="#ffffff" if strong
                                      else theme.token("ink", mode))))

    fig.update_layout(
        annotations=ann, height=330, margin=dict(l=70, r=20, t=10, b=40),
        xaxis=dict(side="top", showgrid=False, ticks="",
                   tickfont=dict(size=11,
                                 color=theme.token("ink-secondary", mode))),
        yaxis=dict(autorange="reversed", showgrid=False, ticks="",
                   tickfont=dict(size=11,
                                 color=theme.token("ink-secondary", mode))))
    theme.apply(fig, mode)
    fig._clamped = clamped   # read by the caller for the caption
    return fig


def win_loss(h2h: pd.DataFrame, selected: str, mode: str) -> go.Figure:
    if h2h.empty:
        return theme.empty_figure(mode=mode)

    tally = (h2h.assign(_one=1)
             .pivot_table(index="rival", columns="winner", values="_one",
                          aggfunc="sum", observed=True).fillna(0))
    for col in ("ABHI cheaper", "Rival cheaper"):
        if col not in tally.columns:
            tally[col] = 0
    tally = tally.sort_values("Rival cheaper")

    good = theme.severity("opportunity", mode)["colour"]
    bad = theme.severity("risk", mode)["colour"]
    outline = theme.token("ink", mode)
    widths = [2.5 if r == selected else 0 for r in tally.index]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=tally.index, x=tally["ABHI cheaper"], orientation="h",
        name="ABHI cheaper",
        marker=dict(color=good, line=dict(color=outline, width=widths)),
        hovertemplate="%{y}<br>ABHI cheaper in %{x} segments<extra></extra>"))
    fig.add_trace(go.Bar(
        y=tally.index, x=tally["Rival cheaper"], orientation="h",
        name="Rival cheaper",
        marker=dict(color=bad, line=dict(color=outline, width=widths)),
        hovertemplate="%{y}<br>rival cheaper in %{x} segments<extra></extra>"))

    fig.update_layout(barmode="stack", height=330, bargap=0.35,
                      xaxis_title="Segments compared",
                      margin=dict(l=110, r=20, t=40, b=45),
                      # without this the legend reverses and stops matching the
                      # left-to-right order of the stacked bars
                      legend=dict(traceorder="normal"),
                      yaxis=dict(tickfont=dict(
                          size=11, color=theme.token("ink-secondary", mode))))
    return theme.apply(fig, mode)


def rate_scatter(prem: pd.DataFrame, rival: str, mode: str) -> go.Figure:
    """Premium per lakh against cover — the shape of each insurer's rate card."""
    pair = prem[prem["company_name"].isin([data.FOCAL, rival])]
    if pair.empty:
        return theme.empty_figure(f"No premium rows for {rival}", mode)

    fig = go.Figure()
    for company in [rival, data.FOCAL]:
        sub = pair[pair["company_name"] == company]
        if sub.empty:
            continue
        focal = company == data.FOCAL
        fig.add_trace(go.Scatter(
            x=sub["sum_insured"], y=sub["premium_per_lakh"], mode="markers",
            name=company,
            marker=dict(color=theme.colour_for(company, mode),
                        size=9 if focal else 8,
                        opacity=0.75 if focal else 0.55,
                        line=dict(width=1.5 if focal else 0.5,
                                  color=theme.token("surface", mode))),
            customdata=sub[["age", "si_label"]].astype(str).values,
            hovertemplate=(f"{company}<br>%{{customdata[1]}} cover · age "
                           "%{customdata[0]}<br>Rs %{y:,.0f} per lakh"
                           "<extra></extra>")))

    # Label a spread of slabs rather than every one: 700000 and 750000 sit
    # almost on top of each other on a log axis and their labels collide.
    slabs = sorted(pair["sum_insured"].dropna().unique())
    ticks, last = [], 0.0
    for v in slabs:
        if not ticks or v >= last * 1.6:
            ticks.append(v)
            last = v

    fig.update_layout(
        height=340, xaxis_title="Sum insured",
        yaxis_title="Premium per lakh of cover (Rs)",
        margin=dict(l=76, r=20, t=40, b=45),
        xaxis=dict(type="log", tickvals=ticks,
                   ticktext=[data.cover(v) for v in ticks]))
    return theme.apply(fig, mode)


# ---------------------------------------------------------------------------

def layout(**_):
    return html.Div([
        ui.page_header("Competitor deep dive",
                       "One rival at a time, on the segments both insurers price"),
        _selector(),
        html.Div(id="rv-insights"),
        dbc.Row([
            dbc.Col(ui.section("Index vs rival by segment",
                               ui.graph(theme.empty_figure(), "rv-heat", height=330),
                               note="100 = identical price. Above 100 = ABHI dearer."),
                    md=7),
            dbc.Col(ui.section("Win / loss across all rivals",
                               ui.graph(theme.empty_figure(), "rv-winloss", height=330),
                               note="Outlined bar is the selected rival."),
                    md=5),
        ], className="g-3"),
        ui.section("Rate shape — ABHI against the selected rival",
                   ui.graph(theme.empty_figure(), "rv-scatter", height=340),
                   note="Premium per lakh normalises for cover, so the two rate "
                        "cards can be compared on one scale."),
        html.Div(id="rv-note"),
    ])


@callback(
    Output("rv-insights", "children"),
    Output("rv-heat", "figure"),
    Output("rv-winloss", "figure"),
    Output("rv-scatter", "figure"),
    Output("rv-note", "children"),
    Input("rv-rival", "value"),
    Input("theme-store", "data"),
)
def update(rival, mode):
    mode = theme.normalise(mode)
    h2h = data.get("vw_head_to_head")
    prem = data.get("vw_premium")

    if not rival:
        empty = theme.empty_figure(mode=mode)
        return ui.insight_row([], "rv", mode=mode), empty, empty, empty, None

    sub = h2h[h2h["rival"] == rival]

    found = insights.rival_threat_ranking()
    cards = dbc.Row([dbc.Col(ui.insight_card(i, f"rv-{n}", mode), md=6,
                             className="mb-3")
                     for n, i in enumerate(found)], className="g-3 mb-2")

    heat = h2h_heatmap(sub, rival, mode)
    note = None
    if getattr(heat, "_clamped", False):
        note = ui.caveat(
            f"Some {rival} segments carry an index far outside the plotted "
            f"colour range — the scale is clamped so one extreme cell does not "
            f"flatten the rest. Printed values and hovers are the true numbers. "
            f"The cause is in Data quality: part of this rival's rate table did "
            f"not extract cleanly.", tone="warning")

    return (cards, heat, win_loss(h2h, rival, mode),
            rate_scatter(prem, rival, mode), note)
