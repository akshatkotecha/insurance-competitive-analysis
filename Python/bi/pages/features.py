"""Page 5 — Product features."""

from __future__ import annotations

import dash
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, callback, html

from bi import components as ui
from bi import data, insights, theme

dash.register_page(__name__, path="/features", name="Product features", order=4)

TICK, CROSS, UNKNOWN = "✓", "✗", "—"
NOT_DISCLOSED = "not disclosed"

DISCLOSURE_CAVEAT = (
    "Benefit flags are keyword-derived from brochure text. A tick means the "
    "benefit is described positively in the source document — not that it is "
    "covered under the base plan, and not at any particular limit. The numeric "
    "policy terms below are document-verified and are the sounder basis for "
    "comparison."
)


# ---------------------------------------------------------------------------

def _feature_matrix() -> pd.DataFrame:
    fm = data.get("vw_feature_matrix")
    if fm.empty:
        return fm

    grid = fm.pivot_table(index="feature_name", columns="company_name",
                          values="has_feature", aggfunc="max", observed=True)

    cols = ([data.FOCAL] if data.FOCAL in grid.columns else []) + \
           [c for c in theme.COMPANY_ORDER if c in grid.columns and c != data.FOCAL] + \
           [c for c in grid.columns if c not in theme.COMPANY_ORDER]
    grid = grid[cols]

    fg = data.get("vw_feature_gaps")
    if not fg.empty:
        order = (fg.sort_values("rival_adoption_pct", ascending=False)
                 ["feature_name"].tolist())
        grid = grid.reindex([f for f in order if f in grid.index]
                            + [f for f in grid.index if f not in order])

    shown = grid.map(lambda v: TICK if v == 1 else (CROSS if v == 0 else UNKNOWN))
    return shown.reset_index().rename(columns={"feature_name": "Feature"})


def _matrix_styles(columns, mode: str) -> list[dict]:
    good = theme.severity("opportunity", mode)["colour"]
    bad = theme.severity("risk", mode)["colour"]
    styles = []
    for col in columns:
        if col == "Feature":
            continue
        for mark, colour in ((TICK, good), (CROSS, bad),
                             (UNKNOWN, theme.token("ink-muted", mode))):
            styles.append({
                "if": {"filter_query": f'{{{col}}} = "{mark}"', "column_id": col},
                "color": colour, "textAlign": "center",
                "fontWeight": "700" if mark != UNKNOWN else "400"})
    if data.FOCAL in columns:
        styles.append({"if": {"column_id": data.FOCAL},
                       "backgroundColor": theme.token("focal-tint", mode)})
    return styles


def adoption_bar(mode: str) -> go.Figure:
    fg = data.get("vw_feature_gaps")
    if fg.empty:
        return theme.empty_figure(mode=mode)

    fg = fg.sort_values("rival_adoption_pct")
    is_gap = fg["gap_status"].str.contains("Gap", na=False)

    fig = go.Figure()
    for label, mask, colour in (
            ("Parity — ABHI carries it", ~is_gap, theme.MUTED[mode]),
            ("Gap — ABHI does not", is_gap, theme.severity("risk", mode)["colour"])):
        sub = fg[mask]
        if sub.empty:
            continue
        fig.add_trace(go.Bar(
            x=sub["rival_adoption_pct"], y=sub["feature_name"], orientation="h",
            name=label, marker=dict(color=colour, line=dict(width=0)),
            customdata=sub[["rivals_with", "rivals_total"]].values,
            hovertemplate=("%{y}<br>%{x:.0f}% of rivals "
                           "(%{customdata[0]} of %{customdata[1]})"
                           "<extra></extra>")))

    fig.update_layout(height=340, bargap=0.32,
                      xaxis_title="Share of rivals describing the benefit (%)",
                      margin=dict(l=170, r=20, t=44, b=45),
                      yaxis=dict(tickfont=dict(
                          size=11, color=theme.token("ink-secondary", mode))))
    return theme.apply(fig, mode)


TERM_COLUMNS = ["company_name", "product_name", "waiting_period", "ped_waiting",
                "room_rent", "pre_hospitalization", "post_hospitalization",
                "ambulance_cover"]


def _policy_terms() -> pd.DataFrame:
    pt = data.get("vw_policy_terms")
    if pt.empty:
        return pt
    df = pt[[c for c in TERM_COLUMNS if c in pt.columns]].copy()

    # A genuine NULL is a benefit the brochure never states. Rendering it as 0
    # would read as "no cover", which is a different and wrong claim.
    for col in ("pre_hospitalization", "post_hospitalization"):
        if col in df.columns:
            df[col] = df[col].map(
                lambda v: NOT_DISCLOSED if pd.isna(v) else f"{int(v)} days")
    if "ambulance_cover" in df.columns:
        df["ambulance_cover"] = df["ambulance_cover"].map(
            lambda v: NOT_DISCLOSED if pd.isna(v) else data.inr(v))
    for col in ("waiting_period", "ped_waiting", "room_rent"):
        if col in df.columns:
            df[col] = (df[col].astype("object")
                       .where(df[col].notna(), NOT_DISCLOSED)
                       .replace("", NOT_DISCLOSED))

    focal_first = df["company_name"] != data.FOCAL
    return (df.assign(_o=focal_first).sort_values(["_o", "company_name"])
            .drop(columns="_o"))


# ---------------------------------------------------------------------------

def layout(**_):
    return html.Div(id="ft-body")


@callback(Output("ft-body", "children"), Input("theme-store", "data"))
def render(mode):
    mode = theme.normalise(mode)
    matrix = _feature_matrix()
    terms = _policy_terms()

    undisclosed = [
        {"if": {"filter_query": f'{{{c}}} = "{NOT_DISCLOSED}"', "column_id": c},
         "color": theme.token("ink-muted", mode), "fontStyle": "italic"}
        for c in terms.columns] if not terms.empty else []

    return html.Div([
        ui.page_header("Product features",
                       "Benefit coverage and policy terms, ABHI against six rivals"),

        ui.caveat(DISCLOSURE_CAVEAT, tone="warning"),

        ui.section("Findings",
                   ui.insight_row(insights.feature_gaps(), "ft", width=6,
                                  mode=mode)),

        # Eight insurer columns plus the feature name need the full width —
        # side by side with the chart, the last insurer fell off the edge.
        ui.section("Feature matrix",
                   ui.table(matrix, "ft-matrix", page_size=12,
                            highlight_focal=False,
                            conditional=_matrix_styles(list(matrix.columns), mode)
                            if not matrix.empty else None, mode=mode),
                   note=f"{TICK} described · {CROSS} not described · "
                        f"{UNKNOWN} no data. ABHI column shaded."),

        ui.section("Rival adoption by benefit",
                   ui.graph(adoption_bar(mode), "ft-adoption", height=340),
                   note="Ordered by how widely rivals describe the benefit."),

        ui.section("Policy terms",
                   ui.table(terms, "ft-terms", page_size=8,
                            conditional=undisclosed, mode=mode),
                   note="Document-verified. Blanks are shown as “not disclosed” "
                        "rather than zero — the brochure is silent, which is not "
                        "the same as no cover."),
    ])
