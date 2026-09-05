"""Page 4 — Financial benchmarking."""

from __future__ import annotations

import dash
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from dash import Input, Output, callback, html

from bi import components as ui
from bi import data, insights, theme

dash.register_page(__name__, path="/financials", name="Financial benchmarking",
                   order=3)


def _metrics() -> list[str]:
    ml = data.get("vw_metrics_long")
    return sorted(ml["metric_name"].dropna().unique().tolist())


def _coverage_note() -> str:
    """Stated from the data rather than asserted, so it cannot drift out of
    date when the pipeline re-runs."""
    ml = data.get("vw_metrics_long")
    mc = data.get("vw_metric_coverage")
    if ml.empty:
        return ""
    cov = (ml.groupby("metric_name", observed=True)
           .agg(years=("financial_year", "nunique"),
                companies=("company_name", "nunique")))
    bits = []
    for metric in ("GWP", "ROE"):
        if metric in cov.index:
            r = cov.loc[metric]
            bits.append(f"{metric} holds {int(r['years'])} years across "
                        f"{int(r['companies'])} insurers")
    for metric, r in cov[cov["years"] <= 1].iterrows():
        bits.append(f"{metric} appears for {int(r['years'])} year only "
                    f"({int(r['companies'])} insurers)")
    if (not mc.empty and "cor_years" in mc.columns
            and mc["cor_years"].fillna(0).sum() == 0):
        bits.append("combined ratio is not reported by any insurer")
    return " · ".join(bits) + "."


def _controls():
    metrics = _metrics()
    default = "GWP" if "GWP" in metrics else (metrics[0] if metrics else None)
    return dbc.Card(dbc.CardBody(dbc.Row([
        dbc.Col([
            html.Label("Metric", className="bi-muted",
                       style={"fontSize": "11px", "fontWeight": 700,
                              "textTransform": "uppercase",
                              "letterSpacing": ".04em"}),
            dbc.Select(id="fn-metric",
                       options=[{"label": m, "value": m} for m in metrics],
                       value=default, size="sm", style={"fontSize": "13px"}),
        ], md=3),
        dbc.Col([
            html.Label("Scale", className="bi-muted",
                       style={"fontSize": "11px", "fontWeight": 700,
                              "textTransform": "uppercase",
                              "letterSpacing": ".04em"}),
            dbc.RadioItems(
                id="fn-scale",
                options=[{"label": "Reported value", "value": "value"},
                         {"label": "Indexed to first year (=100)",
                          "value": "indexed"}],
                value="value", inline=True, inputClassName="me-1",
                labelClassName="me-3",
                style={"fontSize": "13px", "paddingTop": "4px"}),
        ], md=6),
    ], className="g-3")), className=f"mb-4 {ui.CARD}")


# ---------------------------------------------------------------------------

def trend(metric: str, scale: str, mode: str) -> go.Figure:
    """One line per insurer on a single set of axes — never small multiples,
    never a second y-scale."""
    if scale == "indexed":
        df = data.get("vw_metrics_growth")
        ycol, ytitle = "indexed_to_base", "Indexed to first year (=100)"
    else:
        df = data.get("vw_metrics_long")
        ycol, ytitle = "metric_value", None

    df = df[df["metric_name"] == metric].dropna(subset=[ycol])
    if df.empty:
        return theme.empty_figure(f"No {metric} history to plot", mode)

    if ytitle is None:
        unit = df["metric_unit"].dropna()
        ytitle = f"{metric} ({unit.iloc[0]})" if not unit.empty else metric

    fig = go.Figure()
    for company in [c for c in theme.COMPANY_ORDER
                    if c in set(df["company_name"]) and c != data.FOCAL]:
        sub = df[df["company_name"] == company].sort_values("fy_number")
        fig.add_trace(go.Scatter(
            x=sub["financial_year"], y=sub[ycol], name=company,
            mode="lines+markers",
            line=dict(color=theme.colour_for(company, mode), width=1.8),
            marker=dict(size=6),
            hovertemplate=f"{company}<br>%{{x}} · %{{y:,.2f}}<extra></extra>"))

    if data.FOCAL in set(df["company_name"]):
        sub = df[df["company_name"] == data.FOCAL].sort_values("fy_number")
        fig.add_trace(go.Scatter(
            x=sub["financial_year"], y=sub[ycol], name=data.FOCAL,
            mode="lines+markers",
            line=dict(color=theme.focal_colour(mode), width=3.5),
            marker=dict(size=9),
            hovertemplate="ABHI<br>%{x} · %{y:,.2f}<extra></extra>"))

    if scale == "indexed":
        fig.add_hline(y=100, line=dict(color=theme.token("axis", mode),
                                       width=1, dash="dot"))

    order = sorted(df["financial_year"].dropna().unique(),
                   key=lambda fy: df.loc[df["financial_year"] == fy,
                                         "fy_number"].iloc[0])
    fig.update_layout(height=380, yaxis_title=ytitle,
                      xaxis=dict(categoryorder="array", categoryarray=order),
                      margin=dict(l=76, r=20, t=44, b=45))
    return theme.apply(fig, mode)


def cagr_bar(metric: str, mode: str) -> go.Figure:
    cg = data.get("vw_metrics_cagr")
    cg = cg[cg["metric_name"] == metric].dropna(subset=["cagr_pct"])
    if cg.empty:
        return theme.empty_figure(
            f"No CAGR for {metric} — a series that starts at or below zero has "
            "no meaningful growth rate", mode)

    cg = cg.sort_values("cagr_pct")
    fig = go.Figure(go.Bar(
        x=cg["cagr_pct"], y=cg["company_name"], orientation="h",
        marker=dict(color=theme.emphasis_colours(cg["company_name"], mode),
                    line=dict(width=0)),
        hovertemplate="%{y}<br>CAGR %{x:.1f}%<extra></extra>"))
    fig.add_vline(x=0, line=dict(color=theme.token("axis", mode), width=1))
    fig.update_layout(height=300, bargap=0.35, xaxis_title="CAGR (%)",
                      margin=dict(l=110, r=20, t=30, b=45),
                      yaxis=dict(tickfont=dict(
                          size=11, color=theme.token("ink-secondary", mode))))
    return theme.apply(fig, mode)


SCORECARD_COLS = ["metric_name", "financial_year", "abhi_value", "rank_position",
                  "peer_count", "peer_avg", "rank_band", "yoy_pct", "cagr_pct"]


def layout(**_):
    return html.Div([
        ui.page_header("Financial benchmarking",
                       "ABHI against its peer group on published financials, "
                       "FY21–FY25"),
        ui.caveat(_coverage_note(), tone="secondary"),
        html.Div(id="fn-head"),
        _controls(),
        dbc.Row([
            dbc.Col(ui.section("Trend",
                               ui.graph(theme.empty_figure(), "fn-trend", height=380),
                               note="One line per insurer on one axis."), md=7),
            dbc.Col(ui.section("Compound annual growth",
                               ui.graph(theme.empty_figure(), "fn-cagr", height=300),
                               note="ABHI in accent, peers muted."), md=5),
        ], className="g-3"),
    ])


@callback(Output("fn-head", "children"), Input("theme-store", "data"))
def render_head(mode):
    mode = theme.normalise(mode)
    sc = data.get("vw_abhi_scorecard")
    board = sc[SCORECARD_COLS].copy() if not sc.empty else sc

    band_style = [
        {"if": {"filter_query": '{rank_band} contains "Bottom"',
                "column_id": "rank_band"},
         "color": theme.severity("risk", mode)["colour"], "fontWeight": "600"},
        {"if": {"filter_query": '{rank_band} contains "Top"',
                "column_id": "rank_band"},
         "color": theme.severity("opportunity", mode)["colour"],
         "fontWeight": "600"},
        {"if": {"filter_query": "{yoy_pct} > 0", "column_id": "yoy_pct"},
         "color": theme.severity("opportunity", mode)["colour"]},
        {"if": {"filter_query": "{yoy_pct} < 0", "column_id": "yoy_pct"},
         "color": theme.severity("risk", mode)["colour"]},
    ]

    return html.Div([
        ui.section("Findings",
                   ui.insight_row(insights.metric_rank_summary(), "fn",
                                  width=6, mode=mode)),
        ui.section("ABHI scorecard",
                   ui.table(board, "fn-scorecard", page_size=10,
                            highlight_focal=False, conditional=band_style,
                            mode=mode),
                   note="Rank is ABHI's position among the peers that report "
                        "that metric — the peer count differs by metric."),
    ])


@callback(
    Output("fn-trend", "figure"),
    Output("fn-cagr", "figure"),
    Input("fn-metric", "value"),
    Input("fn-scale", "value"),
    Input("theme-store", "data"),
)
def update(metric, scale, mode):
    mode = theme.normalise(mode)
    if not metric:
        return theme.empty_figure(mode=mode), theme.empty_figure(mode=mode)
    return trend(metric, scale, mode), cagr_bar(metric, mode)
