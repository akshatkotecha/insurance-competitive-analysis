"""Page 7 — Ask the data.

The same assistant as chatbotsqql.py, on the same routing and query logic:
both front ends call chatbot_core.answer_question(), so a question is answered
identically whichever one asks it. Nothing here generates an answer — the model
is consulted only to route a question it cannot parse deterministically, and
the reply is always built from a parameterised SQL result.

This is the one page that queries the database per request. The rest of the
dashboard reads the business views once at startup; the assistant cannot,
because the question decides the query. chatbot_core.get_conn() hands out one
connection per thread, which is what makes that safe under Dash's threaded
server.
"""

from __future__ import annotations

import dash
import dash_bootstrap_components as dbc
import pandas as pd
from dash import Input, Output, State, callback, dash_table, dcc, html, no_update

from bi import components as ui
from bi import theme

try:
    import chatbot_core as core
    CORE_ERROR = None
except Exception as exc:                                # pragma: no cover
    core = None
    CORE_ERROR = f"{type(exc).__name__}: {exc}"

dash.register_page(__name__, path="/assistant", name="Ask the data", order=6)

EXAMPLES = [
    "Premium for a 40 year old at 10L",
    "Compare ABHI and HDFC ERGO at 10L",
    "ABHI waiting period",
    "Solvency ratio for all insurers",
    "What is a combined ratio?",
]


def _df_payload(df) -> dict | None:
    """DataFrames do not survive a dcc.Store round trip; keep the bits the
    bubble needs."""
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return None
    show = df.copy()
    for col in show.columns:
        if show[col].dtype.name == "category":
            show[col] = show[col].astype(str)
        elif show[col].dtype.kind == "f":
            show[col] = show[col].round(2)
    return {"columns": [str(c) for c in show.columns],
            "records": show.head(60).to_dict("records")}


def _bubble(m: dict, idx: int, mode: str):
    if m["role"] == "user":
        return html.Div(
            html.Div(m["content"], className="bi-chat-user px-3 py-2",
                     style={"borderRadius": "10px", "maxWidth": "78%",
                            "fontSize": "13.5px"}),
            className="d-flex justify-content-end mb-3")

    body = [dcc.Markdown(m["content"],
                         style={"margin": 0, "fontSize": "13.5px"},
                         className="bi-chat-md")]

    if m.get("table"):
        payload = m["table"]
        body.append(html.Div(dash_table.DataTable(
            id=f"chat-tbl-{idx}",
            data=payload["records"],
            columns=[{"name": c.replace("_", " "), "id": c}
                     for c in payload["columns"]],
            page_size=8, style_table={"overflowX": "auto"},
            style_data_conditional=[{"if": {"row_index": "odd"},
                                     "backgroundColor":
                                         theme.token("row-alt", mode)}],
            style_header={"backgroundColor": theme.token("header-bg", mode),
                          "color": theme.token("ink", mode),
                          "fontWeight": "700", "border": "none",
                          "fontSize": "11.5px",
                          "borderBottom": f"1px solid {theme.token('axis', mode)}"},
            style_cell={"fontFamily": theme.FONT, "fontSize": "12px",
                        "padding": "6px 9px", "textAlign": "left",
                        "backgroundColor": theme.token("surface", mode),
                        "color": theme.token("ink", mode), "border": "none",
                        "borderBottom": f"1px solid {theme.token('grid', mode)}"},
        ), className="mt-2"))

    if m.get("fig"):
        body.append(dcc.Graph(figure=m["fig"], config={"displayModeBar": False},
                              style={"height": "320px"}, className="mt-2"))

    if m.get("sql") and m.get("answered"):
        body.append(html.Details([
            html.Summary("The query behind this answer", className="bi-muted",
                         style={"cursor": "pointer", "fontSize": "12px"}),
            dcc.Markdown(f"```sql\n{m['sql']}\n```",
                         style={"fontSize": "11.5px"}),
        ], className="mt-2"))

    meta = []
    if m.get("kind"):
        meta.append(f"routed to “{m['kind']}”")
    if m.get("source"):
        meta.append(f"by {m['source']}")
    if meta:
        body.append(html.Div(" · ".join(meta), className="bi-muted mt-2",
                             style={"fontSize": "11px"}))

    return html.Div(
        html.Div(body, className="bi-chat-bot px-3 py-2",
                 style={"borderRadius": "10px", "maxWidth": "94%"}),
        className="d-flex justify-content-start mb-3")


def layout(**_):
    if core is None:
        return html.Div([
            ui.page_header("Ask the data", "SQL-backed assistant"),
            ui.caveat(f"chatbot_core could not be imported — {CORE_ERROR}",
                      tone="danger"),
        ])

    return html.Div([
        ui.page_header(
            "Ask the data",
            "The same assistant as chatbotsqql.py — every answer is a database "
            "lookup, not generated text"),

        dbc.Card(dbc.CardBody([
            html.Div("Try asking", className="bi-muted mb-2",
                     style={"fontSize": "11px", "fontWeight": 700,
                            "textTransform": "uppercase",
                            "letterSpacing": ".04em"}),
            html.Div([dbc.Button(q, id={"type": "chat-example", "index": i},
                                 size="sm", color="secondary", outline=True,
                                 className="me-2 mb-2",
                                 style={"fontSize": "12px"})
                      for i, q in enumerate(EXAMPLES)]),
        ]), className=f"mb-4 {ui.CARD}"),

        # session, not memory: navigating to another page and back would
        # otherwise wipe the conversation
        dcc.Store(id="chat-history", data=[], storage_type="session"),
        html.Div(id="chat-messages", className="mb-3",
                 style={"minHeight": "120px"}),
        dcc.Loading(html.Div(id="chat-pending"), type="dot"),

        dbc.InputGroup([
            dbc.Input(id="chat-input", placeholder="Ask a question…",
                      debounce=False, style={"fontSize": "13.5px"}),
            dbc.Button("Send", id="chat-send", n_clicks=0, color="primary"),
        ], className="mb-2"),

        html.Div("Premiums are Tier 1, individual cover unless the question "
                 "says otherwise. The assistant answers on premiums, policy "
                 "terms, company financials and definitions.",
                 className="bi-muted", style={"fontSize": "11.5px"}),
    ])


@callback(
    Output("chat-history", "data"),
    Output("chat-input", "value"),
    Input("chat-send", "n_clicks"),
    Input("chat-input", "n_submit"),
    Input({"type": "chat-example", "index": dash.ALL}, "n_clicks"),
    State("chat-input", "value"),
    State("chat-history", "data"),
    State("theme-store", "data"),
    prevent_initial_call=True,
)
def ask(n_clicks, n_submit, example_clicks, typed, history, mode):
    if core is None:
        return no_update, no_update

    trigger = dash.callback_context.triggered_id
    question = typed
    if isinstance(trigger, dict) and trigger.get("type") == "chat-example":
        # an example chip was pressed; ignore the stale n_clicks of the others
        if not any(example_clicks or []):
            return no_update, no_update
        question = EXAMPLES[trigger["index"]]

    if not question or not str(question).strip():
        return no_update, no_update

    history = list(history or [])
    history.append({"role": "user", "content": str(question).strip()})

    try:
        result = core.answer_question(str(question).strip())
    except Exception as exc:
        history.append({"role": "assistant",
                        "content": f"That query failed: `{type(exc).__name__}: "
                                   f"{exc}`",
                        "answered": False})
        return history, ""

    fig = result.get("fig")
    if fig is not None:
        theme.apply(fig, mode)
        # chatbot_core titles its figures, and the dashboard template parks the
        # legend just above the plot — the two collide. In a chat bubble the
        # legend reads fine underneath.
        fig.update_layout(
            legend=dict(orientation="h", yanchor="top", y=-0.18, x=0,
                        title=dict(text="")),
            margin=dict(l=64, r=20, t=44, b=72))

    history.append({
        "role": "assistant",
        "content": result["answer"],
        "table": _df_payload(result.get("table")),
        "fig": fig.to_dict() if fig is not None else None,
        "sql": result.get("sql"),
        "kind": result.get("kind"),
        "source": result.get("source"),
        "answered": result.get("answered"),
    })
    return history, ""


@callback(
    Output("chat-messages", "children"),
    Input("chat-history", "data"),
    Input("theme-store", "data"),
)
def render_messages(history, mode):
    mode = theme.normalise(mode)
    if not history:
        return html.Div("Ask a question, or pick one of the examples above.",
                        className="bi-muted",
                        style={"fontSize": "13px", "padding": "12px 0"})
    return [_bubble(m, i, mode) for i, m in enumerate(history)]
