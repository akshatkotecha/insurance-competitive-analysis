"""Data layer — load every business-schema view once, then serve from memory.

The whole dataset is small (the largest view is under 9,000 rows) and static
between pipeline runs, so querying per callback would be waste. Everything is
read at startup into a dict of DataFrames; callbacks only ever touch that dict.
Use refresh() to re-read from SQL Server on demand.

Two things SQL Server does that break plotly downstream, both handled here:
NUMERIC/DECIMAL columns arrive as decimal.Decimal (arithmetic against floats
raises), and every categorical axis this dashboard uses — age_band, si_label —
sorts wrong alphabetically. Ordering is applied centrally rather than being
re-derived in each figure.
"""

from __future__ import annotations

import threading
from datetime import datetime
from decimal import Decimal

import pandas as pd
import pyodbc

# Server, database and auth live in Python/db.py, which reads them from the
# environment — one definition for the dashboard, both chatbots and every
# pipeline stage.
from db import CONN_STR, describe  # noqa: F401

# ---------------------------------------------------------------------------
# What we load. Views only — never the base tables.
# ---------------------------------------------------------------------------

VIEWS = [
    "vw_abhi_vs_market",
    "vw_premium",
    "vw_price_grid",
    "vw_head_to_head",
    "vw_peer_comparison",
    "vw_metrics_long",
    "vw_metrics_growth",
    "vw_metrics_cagr",
    "vw_metric_rank",
    "vw_abhi_scorecard",
    "vw_policy_terms",
    "vw_feature_matrix",
    "vw_feature_gaps",
    "vw_data_quality",
    "vw_metric_coverage",
]

FOCAL = "ABHI"

# vw_premium carries a 00-17 band that vw_abhi_vs_market does not. It is listed
# first so those rows keep a defined position instead of dropping out of a
# categorical cast.
AGE_BAND_ORDER = ["00-17", "18-25", "26-35", "36-45", "46-55", "56-65", "66+"]

# Comparison basis stated on every pricing page.
BASIS = "Tier 1 · individual cover (1 adult, 0 children) · 1-year term"

_lock = threading.Lock()
_store: dict[str, pd.DataFrame] = {}
_loaded_at: datetime | None = None


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def _decimal_to_float(df: pd.DataFrame) -> pd.DataFrame:
    """SQL Server NUMERIC arrives as decimal.Decimal inside an object column.
    Plotly and pandas arithmetic both choke on mixing those with floats, so any
    column holding Decimals is converted once, here."""
    for col in df.columns:
        if df[col].dtype != object:
            continue
        non_null = df[col].dropna()
        if non_null.empty:
            # A column nobody reports at all (combined_ratio, icr) comes back as
            # an all-null object column. Cast it too, so charting it yields an
            # empty axis rather than a dtype error.
            df[col] = pd.to_numeric(df[col], errors="coerce").astype(float)
        elif isinstance(non_null.iloc[0], Decimal):
            df[col] = pd.to_numeric(df[col], errors="coerce").astype(float)
    return df


def _apply_orderings(name: str, df: pd.DataFrame) -> pd.DataFrame:
    """Make age_band and si_label sort by meaning rather than by string."""
    if "age_band" in df.columns:
        present = [b for b in AGE_BAND_ORDER if b in set(df["age_band"].dropna())]
        unknown = sorted(set(df["age_band"].dropna()) - set(AGE_BAND_ORDER))
        df["age_band"] = pd.Categorical(df["age_band"], categories=present + unknown,
                                        ordered=True)

    if {"si_label", "sum_insured"} <= set(df.columns):
        order = si_order(df)
        df["si_label"] = pd.Categorical(df["si_label"], categories=order, ordered=True)

    return df


def si_order(df: pd.DataFrame) -> list[str]:
    """Cover-slab labels in ascending sum_insured order.

    si_label is not unique against sum_insured across the whole database —
    700000 and 750000 both render as "7 L" — so labels are de-duplicated on
    first (i.e. cheapest) appearance rather than assumed distinct.
    """
    if not {"si_label", "sum_insured"} <= set(df.columns):
        return []
    pairs = (df[["sum_insured", "si_label"]]
             .dropna()
             .drop_duplicates()
             .sort_values("sum_insured"))
    seen, order = set(), []
    for label in pairs["si_label"]:
        if label not in seen:
            seen.add(label)
            order.append(label)
    return order


def load(force: bool = False) -> dict[str, pd.DataFrame]:
    """Return the view store, loading it on first use."""
    global _loaded_at
    with _lock:
        if _store and not force:
            return _store

        conn = pyodbc.connect(CONN_STR)
        try:
            fresh = {}
            for view in VIEWS:
                df = pd.read_sql(f"SELECT * FROM business.{view}", conn)
                fresh[view] = _apply_orderings(view, _decimal_to_float(df))
        finally:
            conn.close()

        _store.clear()
        _store.update(fresh)
        _loaded_at = datetime.now()
        return _store


def refresh() -> dict[str, pd.DataFrame]:
    return load(force=True)


def loaded_at() -> str:
    return _loaded_at.strftime("%d %b %Y %H:%M:%S") if _loaded_at else "not loaded"


def get(view: str) -> pd.DataFrame:
    """A copy of one view, so callers can mutate freely without poisoning the
    shared store."""
    return load()[view].copy()


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def inr(value, prefix: str = "Rs ") -> str:
    """Indian digit grouping: 1234567 -> 'Rs 12,34,567'."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    n = int(round(float(value)))
    sign = "-" if n < 0 else ""
    s = str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join(groups) + "," + tail
    return f"{sign}{prefix}{s}"


def signed_inr(value) -> str:
    """Gap figures read better with an explicit + on the dearer side."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    return ("+" if float(value) > 0 else "") + inr(value)


def cover(sum_insured) -> str:
    """Rupee cover as a slab label: 1000000 -> '10 L', 10000000 -> '1 Cr'.

    Computed from the number rather than read from si_label, because si_label
    collides (700000 and 750000 are both "7 L") and this is used where the
    distinction matters.
    """
    if sum_insured is None or pd.isna(sum_insured):
        return "—"
    v = float(sum_insured)
    if v >= 10_000_000:
        return f"{v / 10_000_000:g} Cr"
    return f"{v / 100_000:g} L"


def pct(value, digits: int = 1) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{float(value):.{digits}f}%"


def num(value, digits: int = 1) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{float(value):,.{digits}f}"
