"""Reusable UI pieces: insight cards, KPI tiles, tables, page scaffolding.

Chrome is styled through the CSS custom properties in theme.css_variables(),
never with baked hex, so flipping the theme restyles everything already on
screen without rebuilding a layout. The exception is anything plotly draws and
anything DataTable writes as inline style — those take an explicit mode.

The insight card is the important one. A finding is rendered headline-first,
supporting numbers beneath, colour-coded by severity — and always with a text
label and icon beside the colour, never colour alone. The DataFrame that
justifies it hangs off a collapsible, so a reader goes from claim to rows in
one click.
"""

from __future__ import annotations

import dash_bootstrap_components as dbc
import pandas as pd
from dash import dash_table, dcc, html

from . import data, theme
from .insights import Insight

CARD = "bi-card shadow-sm"


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

def _table_styles(mode: str | None):
    t = lambda k: theme.token(k, mode)  # noqa: E731
    return dict(
        style_header={"backgroundColor": t("header-bg"), "color": t("ink"),
                      "fontWeight": "700", "border": "none", "fontSize": "12px",
                      "borderBottom": f"1px solid {t('axis')}"},
        style_cell={"fontFamily": theme.FONT, "fontSize": "12.5px",
                    "padding": "7px 10px", "textAlign": "left",
                    "backgroundColor": t("surface"), "color": t("ink"),
                    "border": "none", "borderBottom": f"1px solid {t('grid')}",
                    "maxWidth": "220px", "textOverflow": "ellipsis"},
    )


def _prepare(df: pd.DataFrame) -> pd.DataFrame:
    show = df.copy()
    for col in show.columns:
        if show[col].dtype.name == "category":
            show[col] = show[col].astype(str)
        elif show[col].dtype.kind == "f":
            # SQL Server hands back full precision (peer_avg arrives as
            # 17218.033333); two decimals is the most any figure here means
            show[col] = show[col].round(2)
    return show


def table(df: pd.DataFrame, tid: str, page_size: int = 15,
          highlight_focal: bool = True, conditional=None,
          wrap_columns: list[str] | None = None,
          mode: str | None = None) -> html.Div:
    if df is None or df.empty:
        return dbc.Alert("No rows for this selection.", color="secondary",
                         className="small border-0")

    show = _prepare(df)
    t = lambda k: theme.token(k, mode)  # noqa: E731

    cond = [{"if": {"row_index": "odd"}, "backgroundColor": t("row-alt")}]
    if highlight_focal and "company_name" in show.columns:
        cond.append({"if": {"filter_query": f'{{company_name}} = "{data.FOCAL}"'},
                     "backgroundColor": t("focal-tint"), "fontWeight": "600"})
    if conditional:
        cond.extend(conditional)

    # columns whose whole point is the sentence they carry wrap rather than clip
    cell_conditional = [
        {"if": {"column_id": c}, "whiteSpace": "normal", "height": "auto",
         "maxWidth": "460px", "minWidth": "220px"}
        for c in (wrap_columns or []) if c in show.columns]

    return dash_table.DataTable(
        id=tid, data=show.to_dict("records"),
        columns=[{"name": c.replace("_", " "), "id": c} for c in show.columns],
        page_size=page_size, sort_action="native",
        style_table={"overflowX": "auto"},
        style_cell_conditional=cell_conditional,
        style_data_conditional=cond,
        **_table_styles(mode),
    )


def _evidence_table(df: pd.DataFrame, tid: str, mode: str | None) -> html.Div:
    if df is None or df.empty:
        return html.Div("No supporting rows.", className="bi-muted small p-2")
    show = _prepare(df)
    t = lambda k: theme.token(k, mode)  # noqa: E731
    return dash_table.DataTable(
        id=tid, data=show.to_dict("records"),
        columns=[{"name": c.replace("_", " "), "id": c} for c in show.columns],
        page_size=12, style_table={"overflowX": "auto"},
        style_data_conditional=[{"if": {"row_index": "odd"},
                                 "backgroundColor": t("row-alt")}],
        **_table_styles(mode),
    )


# ---------------------------------------------------------------------------
# Insight cards
# ---------------------------------------------------------------------------

def insight_card(ins: Insight, idx: str, mode: str | None = None) -> dbc.Card:
    sev = theme.severity(ins.severity, mode)
    body = [
        html.Div([
            html.Span(f"{sev['icon']} {sev['label']}",
                      style={"color": sev["colour"], "fontWeight": 700,
                             "fontSize": "11px", "letterSpacing": ".04em",
                             "textTransform": "uppercase"}),
            html.Span(ins.source.replace("_", " "), className="bi-muted",
                      style={"fontSize": "11px", "float": "right"}),
        ], className="mb-2"),
        html.Div(ins.headline, style={"fontWeight": 650, "fontSize": "15px",
                                      "lineHeight": 1.35,
                                      "color": "var(--bi-ink)"}),
        html.Div(ins.detail, className="mt-1 bi-secondary",
                 style={"fontSize": "13px", "lineHeight": 1.5}),
    ]
    if ins.evidence is not None and not ins.evidence.empty:
        body.append(html.Details([
            html.Summary(f"Evidence — {len(ins.evidence)} row(s)",
                         className="bi-muted",
                         style={"cursor": "pointer", "fontSize": "12px",
                                "marginTop": "10px"}),
            html.Div(_evidence_table(ins.evidence, f"ev-{idx}", mode),
                     className="mt-2"),
        ]))
    return dbc.Card(dbc.CardBody(body), className="h-100 shadow-sm",
                    style={"borderLeft": f"4px solid {sev['border']}",
                           "backgroundColor": sev["bg"],
                           "border": "1px solid var(--bi-border)"})


def insight_row(insights: list[Insight], prefix: str, width: int = 12,
                mode: str | None = None) -> html.Div:
    if not insights:
        return dbc.Alert("No findings for this view.", color="secondary",
                         className="small border-0")
    cards = [insight_card(ins, f"{prefix}-{i}", mode)
             for i, ins in enumerate(insights)]

    # Full-width cards stack, so equal-height stretching would only pad every
    # card out to the tallest. Side-by-side keeps it, because there a ragged
    # bottom edge reads as a mistake.
    if width >= 12:
        return html.Div([html.Div(c, className="mb-3") for c in cards])
    return dbc.Row([dbc.Col(c, md=width, className="mb-3") for c in cards],
                   className="g-3")


# ---------------------------------------------------------------------------
# KPI tiles
# ---------------------------------------------------------------------------

def kpi(label: str, value: str, sub: str = "", tone: str = "neutral",
        mode: str | None = None) -> dbc.Card:
    colour = {"good": theme.severity("opportunity", mode)["colour"],
              "bad": theme.severity("risk", mode)["colour"]}.get(
                  tone, "var(--bi-ink)")
    return dbc.Card(dbc.CardBody([
        html.Div(label, className="bi-muted",
                 style={"fontSize": "11px", "letterSpacing": ".04em",
                        "textTransform": "uppercase", "fontWeight": 600}),
        html.Div(value, style={"fontSize": "26px", "fontWeight": 700,
                               "color": colour, "lineHeight": 1.15,
                               "marginTop": "4px"}),
        html.Div(sub, className="bi-secondary",
                 style={"fontSize": "11.5px", "marginTop": "2px",
                        "lineHeight": 1.35}),
    ], className="py-3"), className=f"h-100 {CARD}")


# ---------------------------------------------------------------------------
# Page scaffolding
# ---------------------------------------------------------------------------

def page_header(title: str, subtitle: str = "") -> html.Div:
    return html.Div([
        html.H4(title, className="mb-1",
                style={"fontWeight": 700, "color": "var(--bi-ink)"}),
        html.Div(subtitle, className="bi-secondary",
                 style={"fontSize": "13px"}),
    ], className="mb-3 pb-2",
        style={"borderBottom": "1px solid var(--bi-grid)"})


def section(title: str, *children, note: str = "") -> html.Div:
    head = [html.H6(title, className="mb-0",
                    style={"fontWeight": 700, "color": "var(--bi-ink)"})]
    if note:
        head.append(html.Div(note, className="bi-muted",
                             style={"fontSize": "11.5px"}))
    return html.Div([html.Div(head, className="mb-2"), *children],
                    className="mb-4")


def graph(fig, gid: str, height: int = 380) -> dcc.Graph:
    return dcc.Graph(id=gid, figure=fig, config={"displayModeBar": False},
                     style={"height": f"{height}px"})


def caveat(text: str, tone: str = "warning") -> dbc.Alert:
    return dbc.Alert(text, color=tone, className="small mb-3 border-0",
                     style={"fontSize": "12.5px"})
