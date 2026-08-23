"""
Insurance competitive-intelligence dashboard — Dash front end.

    python dash_app.py

Same five sections as the old Streamlit dashboard (Position, Peer
comparison, Trends, Pricing detail, Ask), rebuilt in Dash for full control
over styling — a real light/dark theme (toggle top-right, both hand-tuned,
not just an inverted default) and a CSS design system in assets/style.css
instead of fighting a component library's built-in theming.

Connects live to the same SQL Server views on every request; the chat tab
uses chatbot_core.answer_question(), the same routing/query logic as
chatbotsqql.py, so a question is answered identically in both front ends.
"""

import json
from functools import lru_cache

import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from dash import Dash, Input, Output, State, dash_table, dcc, html, no_update

import chatbot_core as core

# =====================================
# CONFIG
# =====================================

FOCAL_COMPANY = "ABHI"

AGE_BAND_ORDER = ["18-25", "26-35", "36-45", "46-55", "56-65", "66+"]
SI_LABEL_ORDER = ["10 L", "15 L", "20 L", "25 L", "50 L", "75 L", "1 Cr", "2 Cr"]

# categorical palette, fixed order — ABHI gets the first, most prominent
# slot since it is the focal company on every chart. Same hex in both
# themes (validated for contrast against both surfaces).
COMPANY_COLORS = {
    "ABHI":          "#2a78d6",
    "Bajaj Allianz":  "#eb6834",
    "HDFC ERGO":      "#1baf7a",
    "ICICI Lombard":  "#eda100",
    "Niva Bupa":      "#e87ba4",
    "Star Health":    "#008300",
    "Tata AIG":       "#4a3aa7",
}

# status palette — fixed, never themed
GOOD = "#0ca30c"
CRITICAL = "#d03b3b"
GREY_STATUS = "#8a8a8a"

# chart chrome that DOES flip with theme (plotly can't read CSS vars)
CHART_THEME = {
    "light": {"ink": "#52514e", "muted": "#898781", "grid": "#e1e0d9", "axis": "#c3c2b7"},
    "dark":  {"ink": "#c3c2b7", "muted": "#898781", "grid": "#2c2c2a", "axis": "#383835"},
}

# =====================================
# DATA
# =====================================

@lru_cache(maxsize=1)
def load_position():
    return pd.read_sql("SELECT * FROM business.vw_abhi_vs_market", core.get_conn())


@lru_cache(maxsize=1)
def load_data_quality():
    return pd.read_sql("SELECT * FROM business.vw_data_quality", core.get_conn())


@lru_cache(maxsize=1)
def load_peer_comparison():
    return pd.read_sql("SELECT * FROM business.vw_peer_comparison", core.get_conn())


@lru_cache(maxsize=1)
def load_metrics_long():
    return pd.read_sql("SELECT * FROM business.vw_metrics_long", core.get_conn())


@lru_cache(maxsize=1)
def load_premium():
    return pd.read_sql("SELECT * FROM business.vw_premium", core.get_conn())


def df_payload(df):
    """JSON-safe {columns, records} for a dcc.Store — routes through
    pandas' own to_json so Decimal/NaN/Timestamp all come out clean."""
    if df is None:
        return None
    return {"columns": list(df.columns), "records": json.loads(df.to_json(orient="records"))}


# =====================================
# CHART HELPERS
# =====================================

def style_fig(fig, theme):
    t = CHART_THEME.get(theme, CHART_THEME["light"])
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=t["ink"], size=13),
        legend=dict(font=dict(color=t["ink"]), title_font=dict(color=t["ink"])),
        margin=dict(l=10, r=10, t=30, b=10),
    )
    fig.update_xaxes(gridcolor=t["grid"], linecolor=t["axis"], zerolinecolor=t["axis"],
                      title_font=dict(color=t["ink"]), tickfont=dict(color=t["muted"]))
    fig.update_yaxes(gridcolor=t["grid"], linecolor=t["axis"], zerolinecolor=t["axis"],
                      title_font=dict(color=t["ink"]), tickfont=dict(color=t["muted"]))
    return fig


def make_heatmap(theme):
    pos = load_position()
    t = CHART_THEME.get(theme, CHART_THEME["light"])

    grid = pos.pivot(index="age_band", columns="si_label", values="price_index")
    grid = grid.reindex(index=AGE_BAND_ORDER, columns=SI_LABEL_ORDER)
    hover = pos.pivot(index="age_band", columns="si_label", values="position")
    hover = hover.reindex(index=AGE_BAND_ORDER, columns=SI_LABEL_ORDER).fillna("no data")
    cell_text = grid.map(lambda v: "" if pd.isna(v) else f"{v:.0f}")

    fig = go.Figure(go.Heatmap(
        z=grid.values, x=grid.columns, y=grid.index,
        zmin=50, zmax=150, xgap=3, ygap=3,
        colorscale=[
            [0.0, GOOD], [0.4, GOOD],
            [0.4, GREY_STATUS], [0.55, GREY_STATUS],
            [0.55, CRITICAL], [1.0, CRITICAL],
        ],
        colorbar=dict(title="Price<br>index", tickvals=[60, 90, 105, 140],
                       tickfont=dict(color=t["muted"]), title_font=dict(color=t["ink"])),
        text=cell_text.values, texttemplate="%{text}",
        textfont=dict(size=12, color="white"),
        customdata=hover.values,
        hovertemplate="Age %{y}, cover %{x}<br>Price index: %{z:.1f}<br>Position: %{customdata}<extra></extra>",
    ))
    fig.update_layout(height=420, xaxis_title="Sum insured", yaxis_title="Age band")
    return style_fig(fig, theme)


def make_trends_fig(metric, theme):
    metrics = load_metrics_long()
    mdf = metrics[metrics["metric_name"] == metric].sort_values("fy_number")
    year_order = (mdf[["financial_year", "fy_number"]]
                  .drop_duplicates().sort_values("fy_number")["financial_year"].tolist())
    unit = mdf["metric_unit"].mode().iat[0] if not mdf.empty else ""

    fig = px.line(
        mdf, x="financial_year", y="metric_value", color="company_name", markers=True,
        category_orders={"financial_year": year_order, "company_name": list(COMPANY_COLORS)},
        color_discrete_map=COMPANY_COLORS,
        labels={"financial_year": "Financial year",
                "metric_value": f"{metric} ({unit})" if unit else metric,
                "company_name": "Insurer"},
    )
    fig.update_traces(line=dict(width=2), marker=dict(size=7))
    fig.update_traces(selector=dict(name=FOCAL_COMPANY), line=dict(width=4))
    fig.update_layout(height=440, hovermode="x unified")
    return style_fig(fig, theme)


def cover_label(si):
    """vw_premium's si_label is a rounded display string, not a 1:1 key —
    two distinct sum_insured values (e.g. 700000 and 750000) both show as
    "7 L". Build the label from the numeric value instead so nothing
    collides or misorders."""
    return f"{si/10000000:g} Cr" if si >= 10000000 else f"{si/100000:g} L"


def make_pricing_fig(tier, composition, companies, theme):
    premium = load_premium()
    filtered = premium[
        (premium["city_tier"] == tier)
        & (premium["composition"] == composition)
        & (premium["company_name"].isin(companies))
    ].copy()

    filtered["cover_label"] = filtered["sum_insured"].map(cover_label)
    order = (filtered[["sum_insured", "cover_label"]].drop_duplicates()
             .sort_values("sum_insured")["cover_label"].tolist())

    grouped = (filtered.groupby(["company_name", "cover_label"], as_index=False)
               .agg(median_ppl=("premium_per_lakh", "median")))

    fig = px.line(
        grouped, x="cover_label", y="median_ppl", color="company_name", markers=True,
        category_orders={"cover_label": order, "company_name": list(COMPANY_COLORS)},
        color_discrete_map=COMPANY_COLORS,
        labels={"cover_label": "Sum insured", "median_ppl": "Median premium per lakh (Rs)",
                "company_name": "Insurer"},
    )
    fig.update_traces(line=dict(width=2), marker=dict(size=7))
    fig.update_traces(selector=dict(name=FOCAL_COMPANY), line=dict(width=4))
    fig.update_layout(height=460, hovermode="x unified")
    return style_fig(fig, theme)


def make_compare_fig(age, amount, tier, composition, theme):
    """Bar chart: premium for every insurer at one exact age × cover ×
    tier × composition — the precise point-comparison the slab-median
    line chart above deliberately smooths away."""
    premium = load_premium()
    filtered = premium[
        (premium["age"] == age) & (premium["sum_insured"] == amount)
        & (premium["city_tier"] == tier) & (premium["composition"] == composition)
    ].drop_duplicates(subset=["company_name"]).sort_values("premium_amount")

    fig = go.Figure()
    if filtered.empty:
        fig.add_annotation(text="No insurer holds a rate for this exact combination.",
                            showarrow=False, font=dict(size=13))
        fig.update_xaxes(visible=False)
        fig.update_yaxes(visible=False)
        fig.update_layout(height=360)
        return style_fig(fig, theme)

    colors = [COMPANY_COLORS.get(c, GREY_STATUS) for c in filtered["company_name"]]
    fig.add_trace(go.Bar(
        x=filtered["company_name"], y=filtered["premium_amount"],
        marker_color=colors,
        text=filtered["premium_amount"].map(lambda v: f"Rs {v:,.0f}"),
        textposition="outside",
        hovertemplate="%{x}<br>Rs %{y:,.0f}<extra></extra>",
    ))
    fig.update_layout(height=400, showlegend=False,
                       yaxis_title="Premium (Rs)", xaxis_title="Insurer")
    fig.update_yaxes(rangemode="tozero")
    return style_fig(fig, theme)


# =====================================
# STATIC CONTENT (built once from cached data — themed purely via CSS)
# =====================================

def kpi_cards():
    pos = load_position()
    below_pct = (pos["price_index"] < 90).mean() * 100
    above_pct = (pos["price_index"] > 105).mean() * 100
    avg_index = pos["price_index"].mean()
    avg_gap = pos["gap_rupees"].mean()
    gap_cls = "good" if avg_gap < 0 else "bad"
    gap_word = "ABHI cheaper" if avg_gap < 0 else "ABHI dearer"

    def card(icon, label, value, delta=None, delta_cls=None):
        children = [
            html.Div([html.Span(icon), html.Span(label)], className="kpi-label"),
            html.Div(value, className="kpi-value"),
        ]
        if delta:
            children.append(html.Div(delta, className=f"kpi-delta {delta_cls}"))
        return html.Div(children, className="kpi-card")

    return html.Div([
        card("📊", "Avg price index", f"{avg_index:.1f}"),
        card("🟢", "Segments below market", f"{below_pct:.0f}%"),
        card("🔴", "Segments above market", f"{above_pct:.0f}%"),
        card("💸", "Avg premium gap", f"Rs {avg_gap:,.0f}", f"{gap_word}", gap_cls),
    ], className="kpi-grid")


def coverage_cards():
    dq = load_data_quality().sort_values("company_name")
    cards = []
    for _, row in dq.iterrows():
        if row["caveat"] == "OK":
            cls, icon, label = "good", "✅", "OK"
        elif row["premium_rows"] == 0:
            cls, icon, label = "critical", "⛔", "No data"
        else:
            cls, icon, label = "warning", "⚠️", "Caveat"
        meta = [html.Div(f"{row['premium_rows']} rows · {row['slabs']} slabs", className="coverage-meta")]
        if row["caveat"] != "OK":
            meta.append(html.Div(row["caveat"], className="coverage-meta"))
        cards.append(html.Div([
            html.Div(row["company_name"], className="coverage-name"),
            html.Span([icon, " ", label], className=f"status-pill {cls}"),
            *meta,
        ], className="coverage-card"))
    return html.Div(cards, className="coverage-grid")


def peer_table():
    peer = load_peer_comparison().sort_values("is_focal", ascending=False).reset_index(drop=True)
    display_cols = {
        "company_name": "Insurer", "product_name": "Product",
        "financial_year": "FY", "gwp": "GWP (Rs Cr)", "gdpi": "GDPI (Rs Cr)",
        "net_worth": "Net worth (Rs Cr)", "aum": "AUM (Rs Cr)",
        "market_share": "Market share (%)", "roe": "ROE (%)", "roa": "ROA (%)",
        "solvency_ratio": "Solvency (x)", "combined_ratio": "Combined ratio (%)",
        "icr": "ICR (%)", "gwp_to_net_worth": "GWP / net worth (x)",
    }
    table = peer[list(display_cols)].rename(columns=display_cols)
    non_numeric = {"Insurer", "Product", "FY"}
    for c in table.columns:
        if c not in non_numeric:
            table[c] = pd.to_numeric(table[c], errors="coerce").map(
                lambda v: "—" if pd.isna(v) else f"{v:,.2f}")

    return dash_table.DataTable(
        data=table.to_dict("records"),
        columns=[{"name": c, "id": c} for c in table.columns],
        style_table={"overflowX": "auto"},
        style_header={"backgroundColor": "var(--surface-2)", "color": "var(--ink)",
                      "fontWeight": "700", "border": "none",
                      "borderBottom": "1px solid var(--border)", "fontSize": "0.82rem"},
        style_cell={"backgroundColor": "var(--surface)", "color": "var(--ink-secondary)",
                    "border": "none", "borderBottom": "1px solid var(--border)",
                    "padding": "10px 14px", "fontSize": "0.85rem",
                    "fontFamily": "inherit", "textAlign": "left"},
        style_data_conditional=[{
            "if": {"filter_query": f'{{Insurer}} = "{FOCAL_COMPANY}"'},
            "backgroundColor": "var(--accent-soft)", "fontWeight": "700", "color": "var(--ink)",
        }],
        style_as_list_view=True,
    )


def try_asking_block():
    slabs = core.load_slabs()
    slab_text = ", ".join(
        f"{s/10000000:g}Cr" if s >= 10000000 else f"{s/100000:g}L" for s in slabs)
    age_lo, age_hi = core.load_age_range()
    return html.Details([
        html.Summary("💬 Try asking"),
        html.Ul([
            html.Li([html.B("Premiums: "), "Premium for a 40 year old at 10L · Cheapest cover at 5L for a 30 year old · Compare ABHI and HDFC ERGO at 10L"]),
            html.Li([html.B("Policy terms: "), "ABHI waiting period · Room rent limit for Star Health · Does Tata AIG cover maternity"]),
            html.Li([html.B("Company financials: "), "ABHI GWP · Solvency ratio for all insurers · ICICI Lombard ROE"]),
            html.Li([html.B("Definitions: "), "What does sum insured mean? · What is a combined ratio?"]),
        ]),
        html.Div(f"Cover slabs: {slab_text}  ·  Ages: {age_lo}–{age_hi}  ·  Tier 1, individual cover unless a floater is asked for",
                 style={"fontSize": "0.78rem", "color": "var(--muted)", "marginTop": "6px"}),
    ], className="try-asking card")


# =====================================
# APP
# =====================================

app = Dash(__name__, title="Health Insurance Dashboard")
server = app.server


def filter_block(label, component):
    return html.Div([html.Div(label, className="filter-label"), component], className="filter-block")


def tabs_layout():
    premium = load_premium()
    metric_names = sorted(load_metrics_long()["metric_name"].unique())
    default_metric = "GWP" if "GWP" in metric_names else metric_names[0]
    tiers = sorted(premium["city_tier"].unique())
    compositions = sorted(premium["composition"].unique())
    ages = sorted(int(a) for a in premium["age"].unique())
    amounts = sorted(premium["sum_insured"].unique())
    amount_options = [{"label": cover_label(a), "value": a} for a in amounts]
    default_amount = 1000000 if 1000000 in amounts else amounts[0]
    default_age = 30 if 30 in ages else ages[len(ages) // 2]

    position_tab = html.Div([
        kpi_cards(),
        html.Div([
            html.H3("Price index by age band × cover"),
            html.Div([
                html.Span([html.Span(className="dot", style={"background": GOOD}), "Below 90 — aggressively priced"]),
                html.Span([html.Span(className="dot", style={"background": GREY_STATUS}), "90–105 — at market"]),
                html.Span([html.Span(className="dot", style={"background": CRITICAL}), "Above 105 — above market"]),
            ], className="legend-row"),
            dcc.Graph(id="heatmap-graph", config={"displayModeBar": False}),
        ], className="card"),
        html.Div([
            html.H3("Data coverage"),
            coverage_cards(),
        ], className="card"),
    ], className="tab-panel")

    peer_tab = html.Div([
        html.Div([
            html.H3("Peer comparison — FY25"),
            html.Div(f"Latest financial year per insurer — {FOCAL_COMPANY} highlighted.", className="caption"),
            html.Div(peer_table(), className="table-wrap"),
        ], className="card"),
    ], className="tab-panel")

    trends_tab = html.Div([
        html.Div([
            html.Div([
                filter_block("Metric", dcc.Dropdown(
                    id="metric-dropdown",
                    options=[{"label": m, "value": m} for m in metric_names],
                    value=default_metric, clearable=False, className="dash-dropdown")),
            ], className="filters-row"),
            html.Div("Only GWP and ROE have full coverage across every insurer and year; "
                     "other metrics may have gaps for some insurers.", className="caption"),
            dcc.Graph(id="trends-graph", config={"displayModeBar": False}),
        ], className="card"),
    ], className="tab-panel")

    pricing_tab = html.Div([
        html.Div([
            html.Div([
                filter_block("City tier", dcc.Dropdown(
                    id="tier-dropdown", options=[{"label": t, "value": t} for t in tiers],
                    value="Tier 1" if "Tier 1" in tiers else tiers[0], clearable=False, className="dash-dropdown")),
                filter_block("Composition", dcc.Dropdown(
                    id="composition-dropdown", options=[{"label": c, "value": c} for c in compositions],
                    value=compositions[0], clearable=False, className="dash-dropdown")),
                filter_block("Insurers", dcc.Checklist(
                    id="insurer-checklist",
                    options=[{"label": f" {c}", "value": c} for c in COMPANY_COLORS],
                    value=list(COMPANY_COLORS), className="filter-checklist")),
            ], className="filters-row"),
            html.Div("One line per insurer — median premium per lakh of cover across each sum-insured slab.",
                     className="caption"),
            dcc.Graph(id="pricing-graph", config={"displayModeBar": False}),
        ], className="card"),
        html.Div([
            html.H3("Compare premium across insurers"),
            html.Div([
                filter_block("Age", dcc.Dropdown(
                    id="age-dropdown", options=[{"label": f"{a} years", "value": a} for a in ages],
                    value=default_age, clearable=False, searchable=True, className="dash-dropdown")),
                filter_block("Sum insured", dcc.Dropdown(
                    id="amount-dropdown", options=amount_options,
                    value=default_amount, clearable=False, searchable=True, className="dash-dropdown")),
            ], className="filters-row"),
            html.Div("Premium held by every insurer for this exact age × cover × tier × "
                     "composition, cheapest first — uses the city tier and composition filters above.",
                     className="caption"),
            dcc.Graph(id="compare-graph", config={"displayModeBar": False}),
        ], className="card"),
    ], className="tab-panel")

    ask_tab = html.Div([
        html.Div([
            html.H3("Ask the database"),
            html.Div("Same SQL-only assistant as chatbotsqql.py — every answer is a direct lookup, "
                      "nothing is generated.", className="caption"),
            try_asking_block(),
            dcc.Store(id="chat-history", data=[]),
            html.Div([html.Div("Ask something to get started.", className="chat-empty")],
                     id="chat-messages", className="chat-messages"),
            html.Div([
                dcc.Input(id="chat-input", type="text", placeholder="Ask a question",
                          debounce=False, n_submit=0),
                html.Button("Send", id="chat-send", n_clicks=0, className="chat-send-btn"),
            ], className="chat-input-row"),
        ], className="card"),
    ], className="tab-panel")

    tab_style = {"padding": "10px 4px", "color": "var(--muted)", "border": "none",
                 "borderBottom": "2px solid transparent", "fontWeight": "600"}
    tab_selected_style = {"padding": "10px 4px", "color": "var(--accent)", "border": "none",
                           "borderBottom": "2px solid var(--accent)", "fontWeight": "700",
                           "backgroundColor": "transparent"}

    return dcc.Tabs(id="main-tabs", value="position", className="dash-tabs", children=[
        dcc.Tab(label="📍 Position", value="position", children=[position_tab],
                style=tab_style, selected_style=tab_selected_style),
        dcc.Tab(label="🤝 Peer comparison", value="peer", children=[peer_tab],
                style=tab_style, selected_style=tab_selected_style),
        dcc.Tab(label="📈 Trends", value="trends", children=[trends_tab],
                style=tab_style, selected_style=tab_selected_style),
        dcc.Tab(label="💰 Pricing detail", value="pricing", children=[pricing_tab],
                style=tab_style, selected_style=tab_selected_style),
        dcc.Tab(label="💬 Ask", value="ask", children=[ask_tab],
                style=tab_style, selected_style=tab_selected_style),
    ])


app.layout = html.Div(id="app-root", className="app-root", **{"data-theme": "light"}, children=[
    dcc.Store(id="theme-store", storage_type="local", data="light"),
    html.Div([
        html.Div([
            html.H1("Health insurance — competitive intelligence", className="app-title"),
            html.P("ABHI vs. the market, built off business.vw_ views in INSURANCEDB.", className="app-subtitle"),
        ]),
        html.Button(["🌓 ", html.Span("Toggle theme", id="theme-btn-label")],
                    id="theme-toggle", className="theme-toggle", n_clicks=0),
    ], className="app-header"),
    html.Div(tabs_layout(), className="page-body"),
])

# =====================================
# CALLBACKS
# =====================================

@app.callback(Output("theme-store", "data"), Input("theme-toggle", "n_clicks"),
               State("theme-store", "data"), prevent_initial_call=True)
def toggle_theme(n_clicks, current):
    return "dark" if current != "dark" else "light"


@app.callback(Output("app-root", "data-theme"), Input("theme-store", "data"))
def apply_theme(theme):
    return theme or "light"


@app.callback(Output("heatmap-graph", "figure"), Input("theme-store", "data"))
def update_heatmap(theme):
    return make_heatmap(theme)


@app.callback(Output("trends-graph", "figure"),
              Input("metric-dropdown", "value"), Input("theme-store", "data"))
def update_trends(metric, theme):
    return make_trends_fig(metric, theme)


@app.callback(
    Output("pricing-graph", "figure"),
    Input("tier-dropdown", "value"), Input("composition-dropdown", "value"),
    Input("insurer-checklist", "value"), Input("theme-store", "data"),
)
def update_pricing(tier, composition, companies, theme):
    companies = companies or list(COMPANY_COLORS)
    return make_pricing_fig(tier, composition, companies, theme)


@app.callback(
    Output("compare-graph", "figure"),
    Input("age-dropdown", "value"), Input("amount-dropdown", "value"),
    Input("tier-dropdown", "value"), Input("composition-dropdown", "value"),
    Input("theme-store", "data"),
)
def update_compare(age, amount, tier, composition, theme):
    return make_compare_fig(age, amount, tier, composition, theme)


def render_chat_bubble(m):
    children = [dcc.Markdown(m["content"], style={"margin": 0})]
    if m.get("table"):
        payload = m["table"]
        children.append(html.Div(dash_table.DataTable(
            data=payload["records"],
            columns=[{"name": c, "id": c} for c in payload["columns"]],
            style_table={"overflowX": "auto"},
            style_header={"backgroundColor": "var(--surface-2)", "color": "var(--ink)",
                          "fontWeight": "700", "border": "none",
                          "borderBottom": "1px solid var(--border)", "fontSize": "0.78rem"},
            style_cell={"backgroundColor": "var(--surface)", "color": "var(--ink-secondary)",
                        "border": "none", "borderBottom": "1px solid var(--border)",
                        "padding": "8px 10px", "fontSize": "0.8rem",
                        "fontFamily": "inherit", "textAlign": "left"},
            style_as_list_view=True,
        ), className="chat-extra table-wrap"))
    if m.get("fig"):
        children.append(dcc.Graph(figure=m["fig"], config={"displayModeBar": False},
                                   className="chat-extra", style={"height": "320px"}))
    if m.get("sql") and m.get("answered"):
        children.append(html.Details([
            html.Summary("The query behind this answer", style={"fontSize": "0.78rem", "cursor": "pointer"}),
            dcc.Markdown(f"```sql\n{m['sql']}\n```"),
        ], className="chat-extra"))
    return html.Div(children, className=f"chat-bubble {m['role']}")


@app.callback(
    Output("chat-history", "data"), Output("chat-input", "value"),
    Input("chat-send", "n_clicks"), Input("chat-input", "n_submit"),
    State("chat-input", "value"), State("chat-history", "data"), State("theme-store", "data"),
    prevent_initial_call=True,
)
def on_ask(n_clicks, n_submit, question, history, theme):
    if not question or not question.strip():
        return no_update, no_update
    history = list(history or [])
    history.append({"role": "user", "content": question})

    result = core.answer_question(question)
    fig = result["fig"]
    if fig is not None:
        style_fig(fig, theme or "light")
    history.append({
        "role": "assistant",
        "content": result["answer"],
        "table": df_payload(result["table"]),
        "fig": (fig.to_dict() if fig is not None else None),
        "sql": result["sql"],
        "answered": result["answered"],
    })
    return history, ""


@app.callback(Output("chat-messages", "children"), Input("chat-history", "data"))
def render_chat(history):
    if not history:
        return [html.Div("Ask something to get started.", className="chat-empty")]
    return [render_chat_bubble(m) for m in history]


if __name__ == "__main__":
    # debug=True re-enables the dev toolbar + hot reload while iterating
    app.run(debug=False, port=8050)
