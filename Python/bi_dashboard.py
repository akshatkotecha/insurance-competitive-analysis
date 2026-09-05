"""ABHI competitive-intelligence BI dashboard.

    python bi_dashboard.py            then open http://127.0.0.1:8050

Seven pages behind a persistent sidebar, in light or dark. Every view in the
business schema is read once at startup into memory; no BI callback touches
the database. The refresh button re-reads from SQL Server on demand.

The point of the build is the insight layer (bi/insights.py): each page leads
with findings computed from the data, and the charts underneath support them.
The assistant page is the exception to the read-once rule — it runs live
parameterised SQL through chatbot_core, the same module chatbotsqql.py uses.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, State, dcc, html

from bi import data, theme

theme.register_templates()

app = dash.Dash(
    __name__,
    use_pages=True,
    pages_folder="bi/pages",
    # Vanilla Bootstrap 5.3 rather than a Bootswatch theme: it has first-class
    # data-bs-theme support, so one attribute flips every dbc component.
    external_stylesheets=[dbc.themes.BOOTSTRAP, dbc.icons.BOOTSTRAP],
    assets_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "bi", "assets"),
    suppress_callback_exceptions=True,
    title="ABHI Competitive Intelligence",
)

# Tokens are generated from theme.py so the palette has one definition rather
# than one for plotly and a second, drifting one for CSS.
app.index_string = """<!DOCTYPE html>
<html>
<head>
{%metas%}<title>{%title%}</title>{%favicon%}{%css%}
<style>
""" + theme.css_variables() + """
</style>
</head>
<body>
{%app_entry%}
<footer>{%config%}{%scripts%}{%renderer%}</footer>
</body>
</html>"""

SIDEBAR_STYLE = {
    "position": "fixed", "top": 0, "left": 0, "bottom": 0, "width": "246px",
    "padding": "22px 16px", "overflowY": "auto", "zIndex": 100,
}
CONTENT_STYLE = {"marginLeft": "246px", "padding": "26px 30px 60px",
                 "minHeight": "100vh"}

NAV = [
    ("/", "Executive summary", "bi bi-speedometer2"),
    ("/pricing", "Price position", "bi bi-graph-down"),
    ("/rivals", "Competitor deep dive", "bi bi-people"),
    ("/financials", "Financial benchmarking", "bi bi-bank"),
    ("/features", "Product features", "bi bi-list-check"),
    ("/quality", "Data quality", "bi bi-shield-exclamation"),
    ("/assistant", "Ask the data", "bi bi-chat-dots"),
]


def sidebar():
    return html.Div([
        html.Div([
            html.Div("ABHI", style={"fontSize": "20px", "fontWeight": 800,
                                    "color": "var(--bi-focal)",
                                    "letterSpacing": "-.01em"}),
            html.Div("Competitive intelligence", className="bi-secondary",
                     style={"fontSize": "12px"}),
        ], className="mb-4"),

        dbc.Nav(
            [dbc.NavLink([html.I(className=f"{icon} me-2"), label],
                         href=href, active="exact",
                         style={"fontSize": "13.5px", "borderRadius": "6px",
                                "marginBottom": "2px"})
             for href, label, icon in NAV],
            vertical=True, pills=True),

        html.Hr(className="my-4"),

        dbc.Switch(id="theme-toggle", label="Dark mode", value=False,
                   className="small", persistence=True,
                   persistence_type="local"),

        html.Div([
            dbc.Button([html.I(className="bi bi-arrow-clockwise me-2"),
                        "Refresh data"], id="refresh-btn", size="sm",
                       color="secondary", outline=True, className="w-100"),
            html.Div(id="refresh-status", className="mt-2 bi-muted",
                     style={"fontSize": "11px", "lineHeight": 1.4}),
        ], className="mt-3"),

        html.Div([
            html.Div("Comparison basis", className="bi-muted",
                     style={"fontSize": "10.5px", "textTransform": "uppercase",
                            "letterSpacing": ".05em", "fontWeight": 700,
                            "marginBottom": "4px"}),
            html.Div(data.BASIS, className="bi-secondary",
                     style={"fontSize": "11px", "lineHeight": 1.45}),
        ], className="mt-4 pt-3",
            style={"borderTop": "1px solid var(--bi-grid)"}),
    ], className="bi-sidebar", style=SIDEBAR_STYLE)


app.layout = html.Div([
    dcc.Location(id="url"),
    # every figure callback reads this; persistence keeps the choice across
    # reloads without a server round-trip
    dcc.Store(id="theme-store", data="light", storage_type="local"),
    sidebar(),
    html.Div(dash.page_container, style=CONTENT_STYLE),
])


@app.callback(Output("theme-store", "data"), Input("theme-toggle", "value"))
def set_theme(is_dark):
    return "dark" if is_dark else "light"


# Stamping data-bs-theme on <html> is what actually restyles Bootstrap and the
# CSS variables. Done clientside so the flip is immediate and costs no request.
app.clientside_callback(
    """
    function(mode) {
        document.documentElement.setAttribute(
            'data-bs-theme', mode === 'dark' ? 'dark' : 'light');
        return window.dash_clientside.no_update;
    }
    """,
    Output("theme-store", "id"),
    Input("theme-store", "data"),
)


@app.callback(
    Output("refresh-status", "children"),
    Input("refresh-btn", "n_clicks"),
    prevent_initial_call=False,
)
def do_refresh(n_clicks):
    """Reloads every view from SQL Server. Page layouts are functions, so the
    next navigation renders against the new data."""
    if n_clicks:
        try:
            data.refresh()
        except Exception as exc:
            return f"Refresh failed: {type(exc).__name__}"
    else:
        data.load()
    return f"Loaded {data.loaded_at()}"


if __name__ == "__main__":
    print("Loading views from SQL Server ...")
    store = data.load()
    print(f"  {len(store)} views loaded at {data.loaded_at()}")
    print("\nServing on http://127.0.0.1:8050")
    app.run(debug=False, port=8050)
