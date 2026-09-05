"""Page 6 — Data quality.

Reachable from the sidebar like every other page. A dashboard that hides what
its numbers rest on is worse than one with fewer numbers.
"""

from __future__ import annotations

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, callback, html

from bi import components as ui
from bi import data, insights, theme

dash.register_page(__name__, path="/quality", name="Data quality", order=5)


def _analyst_notes(mode: str) -> html.Div:
    """Three standing caveats. The first two are carried in the data itself;
    the third is an analyst note with no column behind it, and is labelled as
    such rather than dressed up as a computed finding."""
    dq = data.get("vw_data_quality")

    care = dq[dq["premium_rows"].fillna(0) == 0]["company_name"].tolist()
    abhi_caveat = dq.loc[dq["company_name"] == data.FOCAL, "caveat"]
    abhi_text = abhi_caveat.iloc[0] if not abhi_caveat.empty else None

    items = []
    if care:
        items.append((", ".join(care) + " holds no premium data",
                      "Zero rate rows, so it is absent from every price "
                      "comparison in this dashboard. It still appears in the "
                      "company list, which is why counts of 'insurers' and "
                      "counts of 'insurers we can price' differ.",
                      "from vw_data_quality"))
    if abhi_text and str(abhi_text).upper() != "OK":
        items.append(("ABHI's own age curve is unreliable",
                      f"{abhi_text}. Treat ABHI's within-product movement from "
                      "one age to the next as indicative; the cross-insurer "
                      "comparisons at a fixed age band are unaffected.",
                      "from vw_data_quality"))

    items.append(("Niva Bupa is the Bronze variant only",
                  "The extracted ReAssure 2.0 rates are the Bronze tier. Higher "
                  "tiers of the same product are not in the dataset, so Niva "
                  "Bupa reads cheaper than its full range would suggest.",
                  "analyst note — not represented in any column"))

    return html.Div([
        dbc.Card(dbc.CardBody([
            html.Div(head, style={"fontWeight": 650, "fontSize": "14px",
                                  "color": "var(--bi-ink)"}),
            html.Div(body, className="mt-1 bi-secondary",
                     style={"fontSize": "13px", "lineHeight": 1.5}),
            html.Div(prov, className="mt-2 bi-muted",
                     style={"fontSize": "11px", "fontStyle": "italic"}),
        ]), className=f"mb-3 {ui.CARD}",
            style={"borderLeft":
                   f"4px solid {theme.severity('neutral', mode)['border']}"})
        for head, body, prov in items])


def layout(**_):
    return html.Div(id="dq-body")


@callback(Output("dq-body", "children"), Input("theme-store", "data"))
def render(mode):
    mode = theme.normalise(mode)
    dq = data.get("vw_data_quality")
    mc = data.get("vw_metric_coverage")

    warnings = insights.data_reliability_warnings() + insights.premium_outliers()

    risk = theme.severity("risk", mode)["colour"]
    dq_style = [
        {"if": {"filter_query": "{premium_rows} = 0"},
         "backgroundColor": theme.severity("risk", mode)["bg"], "color": risk},
        {"if": {"filter_query": '{caveat} != "OK"', "column_id": "caveat"},
         "color": risk, "fontWeight": "600"},
    ]
    mc_style = [
        {"if": {"filter_query": "{gwp_years} = 0", "column_id": "gwp_years"},
         "color": risk, "fontWeight": "600"},
        {"if": {"filter_query": "{roe_years} = 0", "column_id": "roe_years"},
         "color": risk, "fontWeight": "600"},
        {"if": {"filter_query": "{cor_years} = 0", "column_id": "cor_years"},
         "color": theme.token("ink-muted", mode)},
    ]

    return html.Div([
        ui.page_header("Data quality",
                       "What the numbers on the other five pages are resting on"),

        ui.section("Reliability warnings",
                   ui.insight_row(warnings, "dq", width=6, mode=mode),
                   note="Computed from the data on every load, not a static list."),

        ui.section("Standing caveats", _analyst_notes(mode)),

        # Full width each: side by side, the caveat text and cor_years column
        # were both being clipped.
        ui.section("Premium coverage by insurer",
                   ui.table(dq, "dq-coverage", page_size=10,
                            conditional=dq_style, wrap_columns=["caveat"],
                            mode=mode),
                   note="premium_rows is the count of extracted rate rows. The "
                        "caveat column is the reason to distrust a figure, not "
                        "a footnote."),

        ui.section("Financial metric coverage",
                   ui.table(mc, "dq-metrics", page_size=10,
                            conditional=mc_style, mode=mode),
                   note="Years held per insurer. cor_years is combined ratio — "
                        "zero for every insurer, which is why no combined-ratio "
                        "chart exists anywhere in this dashboard."),
    ])
