"""Palette, tokens and figure styling for both themes.

Two selected themes, not one theme and an inversion. Each mode has its own
steps, chosen for its own surface and validated against it with the six-check
validator (OKLab deltaE x100, Machado-2009 CVD simulation at severity 1.0):

  light, 8 insurer slots on #ffffff
      lightness PASS · chroma PASS · CVD 9.1 (target 8) · normal 19.6 (floor 15)
      contrast WARN on aqua 2.82 / yellow 2.17 / magenta 2.69 -> relief rule
  dark, 8 insurer slots on #1a1a19
      lightness PASS · chroma PASS · CVD 8.4 · normal 19.3 · contrast all PASS

One deliberate departure from the reference palette. Its dark violet
(#9085e9) sits far too close to the dark blue: ABHI vs Star Health measured
CVD deltaE 1.9 and normal-vision 9.8, both under the hard floors, which would
have made the two-series scatter unreadable in dark mode. The slot was
re-stepped to #8b47b2, searched rather than guessed, and held to the gate
against all seven other dark slots (worst CVD 9.5, worst normal 17.1,
contrast 3.02). Light mode keeps the reference violet, which already passes.

HTML chrome is themed through CSS custom properties (see css_variables), so a
theme switch restyles the page without rebuilding the layout. Figures bake
their colours in at render time, so every figure builder takes a mode.
"""

from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio

MODES = ("light", "dark")
FOCAL = "ABHI"

# --- chrome and ink --------------------------------------------------------
TOKENS = {
    "light": {
        "surface": "#ffffff",
        "surface-sunk": "#f4f6fa",
        "page": "#f4f5f7",
        "ink": "#0b0b0b",
        "ink-secondary": "#52514e",
        "ink-muted": "#898781",
        "grid": "#e1e0d9",
        "axis": "#c3c2b7",
        "border": "rgba(11,11,11,0.10)",
        "focal-tint": "#e8f0fb",
        "row-alt": "#fbfbfc",
        "header-bg": "#eef1f6",
    },
    "dark": {
        "surface": "#1a1a19",
        "surface-sunk": "#232322",
        "page": "#0d0d0d",
        "ink": "#ffffff",
        "ink-secondary": "#c3c2b7",
        "ink-muted": "#898781",
        "grid": "#2c2c2a",
        "axis": "#383835",
        "border": "rgba(255,255,255,0.12)",
        "focal-tint": "#16283f",
        "row-alt": "#202020",
        "header-bg": "#262625",
    },
}

# --- categorical: fixed slot order, assigned to insurers by name -----------
_SLOTS = {
    "light": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
              "#e87ba4", "#008300", "#4a3aa7", "#e34948"],
    # slot 7 re-stepped from the reference #9085e9 — see module docstring
    "dark":  ["#3987e5", "#d95926", "#199e70", "#c98500",
              "#d55181", "#008300", "#8b47b2", "#e66767"],
}

COMPANY_ORDER = [
    "ABHI", "Bajaj Allianz", "Care Health", "HDFC ERGO",
    "ICICI Lombard", "Niva Bupa", "Star Health", "Tata AIG",
]

COMPANY_COLOURS = {
    mode: {name: slots[i % len(slots)] for i, name in enumerate(COMPANY_ORDER)}
    for mode, slots in _SLOTS.items()
}

# where the axis already names the insurer, hue is redundant: one muted tone
MUTED = {"light": "#b9bcc4", "dark": "#5c5f66"}

# --- diverging: price index, centred on 100 --------------------------------
# Blue (cheaper) to red (dearer) through a neutral grey midpoint, equal steps
# per arm. Never a rainbow; the midpoint is grey so "at market" reads as
# nothing to see.
PRICE_SCALE = {
    "light": [[0.00, "#184f95"], [0.25, "#6da7ec"], [0.50, "#f0efec"],
              [0.75, "#e8908f"], [1.00, "#a52a2a"]],
    "dark":  [[0.00, "#9ec5f4"], [0.25, "#3987e5"], [0.50, "#383835"],
              [0.75, "#c05050"], [1.00, "#e8908f"]],
}
# deliberately not the diverging midpoint: an uncomparable cell must never be
# mistaken for one sitting exactly at market
UNRELIABLE = {"light": "#c9cbd0", "dark": "#4a4a48"}

# --- status: reserved, fixed hues, never reused as a series colour ---------
_STATUS = {"opportunity": "#0ca30c", "risk": "#d03b3b", "neutral": "#898781"}
_STATUS_TINT = {
    "light": {"opportunity": "#eef8ee", "risk": "#fdefef", "neutral": "#f4f4f2"},
    "dark": {"opportunity": "#12251a", "risk": "#2a1618", "neutral": "#242423"},
}
_STATUS_META = {
    "opportunity": ("Opportunity", "▲"),
    "risk": ("Risk", "▼"),
    "neutral": ("Context", "■"),
}

FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'


def normalise(mode: str | None) -> str:
    return mode if mode in MODES else "light"


def token(name: str, mode: str | None = None) -> str:
    return TOKENS[normalise(mode)][name]


def severity(kind: str, mode: str | None = None) -> dict:
    kind = kind if kind in _STATUS else "neutral"
    label, icon = _STATUS_META[kind]
    return {"colour": _STATUS[kind], "label": label, "icon": icon,
            "bg": _STATUS_TINT[normalise(mode)][kind], "border": _STATUS[kind]}


def focal_colour(mode: str | None = None) -> str:
    return COMPANY_COLOURS[normalise(mode)][FOCAL]


def colour_for(company: str, mode: str | None = None) -> str:
    m = normalise(mode)
    return COMPANY_COLOURS[m].get(company, MUTED[m])


def emphasis_colours(companies, mode: str | None = None) -> list[str]:
    """ABHI in accent, everyone else muted — for charts where the axis already
    carries identity and hue would only add noise."""
    m = normalise(mode)
    return [focal_colour(m) if c == FOCAL else MUTED[m] for c in companies]


def price_scale(mode: str | None = None):
    return PRICE_SCALE[normalise(mode)]


def unreliable(mode: str | None = None) -> str:
    return UNRELIABLE[normalise(mode)]


# --- CSS custom properties -------------------------------------------------

def css_variables() -> str:
    """Emit both palettes as custom properties.

    Light lives on bare :root so it also covers the un-stamped default; dark is
    scoped to the explicit stamp Bootstrap already uses, so one attribute swap
    restyles Bootstrap components and this dashboard's own chrome together.
    """
    def block(selector: str, mode: str) -> str:
        rows = [f"    --bi-{k}: {v};" for k, v in TOKENS[mode].items()]
        rows += [f"    --bi-sev-{k}: {v};" for k, v in _STATUS.items()]
        rows += [f"    --bi-sev-{k}-bg: {v};"
                 for k, v in _STATUS_TINT[mode].items()]
        rows.append(f"    --bi-focal: {COMPANY_COLOURS[mode][FOCAL]};")
        return selector + " {\n" + "\n".join(rows) + "\n}"

    return "\n".join([
        block(":root", "light"),
        block('[data-bs-theme="dark"]', "dark"),
        """
body { background: var(--bi-page); color: var(--bi-ink); }
.bi-card { background: var(--bi-surface); border: 1px solid var(--bi-border); }
.bi-sidebar { background: var(--bi-surface);
              border-right: 1px solid var(--bi-grid); }
.bi-muted { color: var(--bi-ink-muted); }
.bi-secondary { color: var(--bi-ink-secondary); }
/* DataTable paints inline styles, so its surfaces are pinned here instead */
[data-bs-theme="dark"] .dash-table-container .dash-spreadsheet-container
  .dash-spreadsheet-inner table { background-color: var(--bi-surface); }
[data-bs-theme="dark"] .dash-table-container .dash-spreadsheet-container
  .dash-spreadsheet-inner td,
[data-bs-theme="dark"] .dash-table-container .dash-spreadsheet-container
  .dash-spreadsheet-inner th { color: var(--bi-ink); }
[data-bs-theme="dark"] .dash-table-container .previous-next-container
  .page-number,
[data-bs-theme="dark"] .dash-table-container .previous-next-container button {
  color: var(--bi-ink-secondary); }
.bi-chat-user { background: var(--bi-focal-tint);
                border: 1px solid var(--bi-border); }
.bi-chat-bot { background: var(--bi-surface);
               border: 1px solid var(--bi-border); }
""",
    ])


# --- plotly templates ------------------------------------------------------

def register_templates() -> None:
    for mode in MODES:
        t = TOKENS[mode]
        tpl = go.layout.Template()
        tpl.layout = go.Layout(
            font=dict(family=FONT, size=12, color=t["ink"]),
            paper_bgcolor=t["surface"],
            plot_bgcolor=t["surface"],
            colorway=_SLOTS[mode],
            margin=dict(l=56, r=20, t=48, b=48),
            title=dict(font=dict(size=14, color=t["ink"]), x=0, xanchor="left"),
            xaxis=dict(showgrid=False, zeroline=False, linecolor=t["axis"],
                       ticks="outside", tickcolor=t["axis"], ticklen=4,
                       tickfont=dict(size=11, color=t["ink-muted"]),
                       title=dict(font=dict(size=11, color=t["ink-secondary"]))),
            yaxis=dict(showgrid=True, gridcolor=t["grid"], gridwidth=1,
                       zeroline=False, linecolor="rgba(0,0,0,0)", ticks="",
                       tickfont=dict(size=11, color=t["ink-muted"]),
                       title=dict(font=dict(size=11, color=t["ink-secondary"]))),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left",
                        x=0, font=dict(size=11, color=t["ink-secondary"]),
                        bgcolor="rgba(0,0,0,0)", title=dict(text="")),
            hoverlabel=dict(font=dict(family=FONT, size=12),
                            bgcolor=t["surface"], bordercolor=t["axis"]),
        )
        pio.templates[f"abhi_{mode}"] = tpl
    pio.templates.default = "abhi_light"


def template(mode: str | None = None) -> str:
    return f"abhi_{normalise(mode)}"


def apply(fig: go.Figure, mode: str | None = None) -> go.Figure:
    """Stamp a figure with the active theme. Called on every figure a callback
    returns, including the ones plotly.express builds inside chatbot_core."""
    m = normalise(mode)
    t = TOKENS[m]
    fig.update_layout(template=template(m), paper_bgcolor=t["surface"],
                      plot_bgcolor=t["surface"],
                      font=dict(family=FONT, color=t["ink"]))
    return fig


def empty_figure(message: str = "No data for this selection",
                 mode: str | None = None) -> go.Figure:
    """Every chart can be filtered down to nothing — say so, rather than
    rendering a bare pair of axes."""
    t = TOKENS[normalise(mode)]
    fig = go.Figure()
    fig.add_annotation(text=message, showarrow=False,
                       font=dict(size=13, color=t["ink-muted"]),
                       xref="paper", yref="paper", x=0.5, y=0.5)
    fig.update_layout(xaxis=dict(visible=False), yaxis=dict(visible=False),
                      paper_bgcolor=t["surface"], plot_bgcolor=t["surface"],
                      margin=dict(l=20, r=20, t=20, b=20), height=260)
    return fig
