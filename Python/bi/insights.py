"""Findings computed from the data.

Each function returns a list of Insight objects. Nothing here is hardcoded —
every headline number is derived from the views at call time, so a pipeline
re-run changes the findings rather than silently invalidating them. A function
that finds nothing returns an empty list; callers render that as "no finding"
rather than inventing one.

Reliability rule used throughout: a price comparison drawn against fewer than
four competitors is not a market average, so segment-level pricing findings are
restricted to competitor_count >= 4. The thin segments are not dropped from the
dataset — they surface in data_reliability_warnings() instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from . import data

MIN_COMPETITORS = 4
PARITY_INDEX = 100.0

SEVERITY_ORDER = {"risk": 0, "opportunity": 1, "neutral": 2}


@dataclass
class Insight:
    headline: str
    detail: str
    severity: str  # 'opportunity' | 'risk' | 'neutral'
    evidence: pd.DataFrame = field(default_factory=pd.DataFrame)
    source: str = ""  # which function produced it, for traceability


def _store(store=None):
    return store if store is not None else data.load()


# ---------------------------------------------------------------------------
# 1. Where does ABHI's price advantage run out?
# ---------------------------------------------------------------------------

def price_position_by_age(store=None) -> list[Insight]:
    """Mean price index per age band, and the band where it crosses 100."""
    df = _store(store)["vw_abhi_vs_market"]
    reliable = df[df["competitor_count"] >= MIN_COMPETITORS]
    if reliable.empty:
        return []

    by_band = (reliable.groupby("age_band", observed=True)
               .agg(segments=("price_index", "size"),
                    avg_index=("price_index", "mean"),
                    avg_gap=("gap_rupees", "mean"))
               .reset_index()
               .sort_values("age_band"))
    if by_band.empty:
        return []

    by_band["avg_index"] = by_band["avg_index"].round(1)
    by_band["avg_gap"] = by_band["avg_gap"].round(0)

    out = []
    above = by_band[by_band["avg_index"] > PARITY_INDEX]

    if above.empty:
        cheapest = by_band.loc[by_band["avg_index"].idxmin()]
        dearest = by_band.loc[by_band["avg_index"].idxmax()]
        out.append(Insight(
            headline="ABHI prices below the market in every age band",
            detail=(f"The index stays under 100 across all {len(by_band)} bands, "
                    f"from {cheapest['avg_index']:.1f} at {cheapest['age_band']} "
                    f"to {dearest['avg_index']:.1f} at {dearest['age_band']}. "
                    f"No crossover point exists in the current data."),
            severity="opportunity", evidence=by_band, source="price_position_by_age"))
        return out

    first_above = above.iloc[0]
    idx = by_band.index.get_loc(first_above.name)
    below = by_band.iloc[idx - 1] if idx > 0 else None

    if below is not None:
        detail = (f"Index averages {below['avg_index']:.1f} at {below['age_band']} "
                  f"({data.signed_inr(below['avg_gap'])} per segment) then "
                  f"{first_above['avg_index']:.1f} at {first_above['age_band']} "
                  f"({data.signed_inr(first_above['avg_gap'])}). "
                  f"Above 100 means ABHI is dearer than the competitor mean.")
        headline = (f"ABHI's price advantage ends at {first_above['age_band']} — "
                    f"the index crosses 100 between {below['age_band']} and "
                    f"{first_above['age_band']}")
    else:
        detail = (f"The oldest-first band {first_above['age_band']} already averages "
                  f"{first_above['avg_index']:.1f}; there is no cheaper band beneath it.")
        headline = f"ABHI prices above the market from {first_above['age_band']} onward"

    out.append(Insight(headline=headline, detail=detail, severity="risk",
                       evidence=by_band, source="price_position_by_age"))
    return out


# ---------------------------------------------------------------------------
# 2. Which cover slabs does the market sell that ABHI does not?
# ---------------------------------------------------------------------------

def slab_coverage_gap(store=None) -> list[Insight]:
    """Compare ABHI's set of sum_insured values against every competitor's."""
    prem = _store(store)["vw_premium"]
    if prem.empty:
        return []

    abhi_slabs = set(prem.loc[prem["company_name"] == data.FOCAL, "sum_insured"].dropna())
    rivals = prem[prem["company_name"] != data.FOCAL]
    if not abhi_slabs or rivals.empty:
        return []

    per_slab = (rivals.groupby("sum_insured", observed=True)["company_name"]
                .nunique()
                .reset_index(name="competitors_selling")
                .sort_values("sum_insured"))
    per_slab["cover"] = per_slab["sum_insured"].map(data.cover)
    per_slab["abhi_sells"] = per_slab["sum_insured"].isin(abhi_slabs)

    missing = per_slab[~per_slab["abhi_sells"]].copy()
    missing = missing.sort_values("competitors_selling", ascending=False)
    if missing.empty:
        return [Insight(
            headline="ABHI covers every slab the market sells",
            detail=f"All {len(per_slab)} competitor slabs are matched by an ABHI slab.",
            severity="neutral", evidence=per_slab, source="slab_coverage_gap")]

    widest = missing.iloc[0]
    entry_market = per_slab["sum_insured"].min()
    entry_abhi = min(abhi_slabs)

    out = []
    out.append(Insight(
        headline=(f"{len(missing)} cover slab(s) sold by the market are missing from "
                  f"ABHI's range — the widest is {widest['cover']}, sold by "
                  f"{int(widest['competitors_selling'])} of "
                  f"{rivals['company_name'].nunique()} competitors"),
        detail=("Missing slabs, most-carried first: "
                + "; ".join(f"{r['cover']} ({int(r['competitors_selling'])} insurers)"
                            for _, r in missing.head(5).iterrows())
                + ("…" if len(missing) > 5 else "") + "."),
        severity="opportunity",
        evidence=missing[["cover", "sum_insured", "competitors_selling"]],
        source="slab_coverage_gap"))

    if entry_abhi > entry_market:
        n_at_entry = int(per_slab.loc[per_slab["sum_insured"] == entry_market,
                                      "competitors_selling"].iloc[0])
        out.append(Insight(
            headline=(f"ABHI does not compete at the entry price point — its cheapest "
                      f"cover is {data.cover(entry_abhi)} against a market entry of "
                      f"{data.cover(entry_market)}"),
            detail=(f"{n_at_entry} competitors sell {data.cover(entry_market)}. "
                    f"A shopper starting at the lowest cover never sees an ABHI quote."),
            severity="opportunity",
            evidence=per_slab[per_slab["sum_insured"] <= entry_abhi][
                ["cover", "sum_insured", "competitors_selling", "abhi_sells"]],
            source="slab_coverage_gap"))

    return out


# ---------------------------------------------------------------------------
# 3. Segments furthest from the market, in rupees
# ---------------------------------------------------------------------------

def widest_gaps(store=None, top_n: int = 5) -> list[Insight]:
    """Rank reliable segments by absolute rupee gap, both directions."""
    df = _store(store)["vw_abhi_vs_market"]
    reliable = df[df["competitor_count"] >= MIN_COMPETITORS].copy()
    if reliable.empty:
        return []

    reliable["abs_gap"] = reliable["gap_rupees"].abs()
    cols = ["age_band", "si_label", "abhi_premium", "market_avg",
            "gap_rupees", "price_index", "competitor_count"]

    cheaper = (reliable[reliable["gap_rupees"] < 0]
               .nlargest(top_n, "abs_gap")[cols])
    dearer = (reliable[reliable["gap_rupees"] > 0]
              .nlargest(top_n, "abs_gap")[cols])

    out = []
    if not cheaper.empty:
        top = cheaper.iloc[0]
        slabs = cheaper["si_label"].astype(str).unique().tolist()
        out.append(Insight(
            headline=(f"Widest undercut: {top['age_band']} at {top['si_label']}, "
                      f"{data.inr(abs(top['gap_rupees']))} below the market mean"),
            detail=(f"ABHI charges {data.inr(top['abhi_premium'])} against a market "
                    f"average of {data.inr(top['market_avg'])} "
                    f"(index {top['price_index']:.1f}, "
                    f"{int(top['competitor_count'])} competitors). "
                    f"The {len(cheaper)} widest undercuts sit at "
                    f"{', '.join(slabs)}."),
            severity="opportunity", evidence=cheaper, source="widest_gaps"))

    if not dearer.empty:
        top = dearer.iloc[0]
        out.append(Insight(
            headline=(f"Widest premium over market: {top['age_band']} at "
                      f"{top['si_label']}, {data.inr(top['gap_rupees'])} above the mean"),
            detail=(f"ABHI charges {data.inr(top['abhi_premium'])} against a market "
                    f"average of {data.inr(top['market_avg'])} "
                    f"(index {top['price_index']:.1f}, "
                    f"{int(top['competitor_count'])} competitors). "
                    f"{len(dearer)} reliable segment(s) price above the market in total."),
            severity="risk", evidence=dearer, source="widest_gaps"))
    else:
        out.append(Insight(
            headline="No reliable segment prices above the market",
            detail=(f"Across {len(reliable)} segments with at least "
                    f"{MIN_COMPETITORS} competitors, ABHI is at or below the "
                    f"competitor mean everywhere."),
            severity="opportunity", evidence=reliable[cols], source="widest_gaps"))

    return out


# ---------------------------------------------------------------------------
# 4. Which rival competes hardest on price?
# ---------------------------------------------------------------------------

def rival_threat_ranking(store=None) -> list[Insight]:
    """Share of shared segments in which each rival undercuts ABHI."""
    h2h = _store(store)["vw_head_to_head"]
    if h2h.empty:
        return []

    grp = h2h.groupby("rival", observed=True)
    ranking = grp.agg(
        segments=("winner", "size"),
        rival_cheaper=("winner", lambda s: int((s == "Rival cheaper").sum())),
        # Median, not mean: a handful of mis-parsed rival rows (see
        # premium_outliers) drag a mean index into the hundreds and would rank
        # the wrong rival as the threat.
        median_index=("index_vs_rival", "median"),
        max_index=("index_vs_rival", "max"),
    ).reset_index()
    ranking["undercut_pct"] = (
        ranking["rival_cheaper"] / ranking["segments"] * 100).round(1)
    ranking["median_index"] = ranking["median_index"].round(1)
    ranking["max_index"] = ranking["max_index"].round(1)
    ranking = ranking.sort_values("undercut_pct", ascending=False)

    top = ranking.iloc[0]
    out = [Insight(
        headline=(f"{top['rival']} is the sharpest price competitor — it undercuts "
                  f"ABHI in {top['undercut_pct']:.0f}% of shared segments "
                  f"({int(top['rival_cheaper'])} of {int(top['segments'])})"),
        detail=("Undercut share by rival: "
                + "; ".join(f"{r['rival']} {r['undercut_pct']:.0f}%"
                            for _, r in ranking.iterrows())
                + f". Median index against {top['rival']} is "
                  f"{top['median_index']:.0f} — above 100 means ABHI is dearer."),
        severity="risk", evidence=ranking, source="rival_threat_ranking")]

    never = ranking[ranking["rival_cheaper"] == 0]
    if not never.empty:
        out.append(Insight(
            headline=(f"ABHI is cheaper in every compared segment against "
                      f"{', '.join(never['rival'])}"),
            detail=(f"{len(never)} rival(s) never undercut ABHI across "
                    f"{int(never['segments'].sum())} compared segments."),
            severity="opportunity", evidence=never, source="rival_threat_ranking"))

    return out


# ---------------------------------------------------------------------------
# 5. Where ABHI ranks on published financials
# ---------------------------------------------------------------------------

def metric_rank_summary(store=None) -> list[Insight]:
    """Rank bands and the biggest year-on-year mover, from the scorecard."""
    sc = _store(store)["vw_abhi_scorecard"]
    if sc.empty:
        return []

    bands = sc["rank_band"].fillna("unclassified")
    top = sc[bands.str.contains("Top", case=False, na=False)]
    bottom = sc[bands.str.contains("Bottom", case=False, na=False)]

    out = []
    if not bottom.empty:
        worst = bottom.sort_values("rank_position", ascending=False).iloc[0]
        out.append(Insight(
            headline=(f"ABHI sits in the bottom third on {len(bottom)} of {len(sc)} "
                      f"benchmarked metrics"),
            detail=(f"Weakest is {worst['metric_name']}: ranked "
                    f"{int(worst['rank_position'])} of {int(worst['peer_count'])} at "
                    f"{data.num(worst['abhi_value'], 2)} {worst['metric_unit']} "
                    f"against a peer average of {data.num(worst['peer_avg'], 2)}. "
                    + (f"No metric reaches the top third."
                       if top.empty else
                       f"{len(top)} metric(s) reach the top third.")),
            severity="risk", evidence=bottom, source="metric_rank_summary"))

    if not top.empty:
        best = top.sort_values("rank_position").iloc[0]
        out.append(Insight(
            headline=(f"ABHI ranks in the top third on {len(top)} metric(s) — "
                      f"best is {best['metric_name']} at rank "
                      f"{int(best['rank_position'])} of {int(best['peer_count'])}"),
            detail=(f"{best['metric_name']} of {data.num(best['abhi_value'], 2)} "
                    f"{best['metric_unit']} against a peer average of "
                    f"{data.num(best['peer_avg'], 2)}."),
            severity="opportunity", evidence=top, source="metric_rank_summary"))

    movers = sc.dropna(subset=["yoy_pct"]).copy()
    if not movers.empty:
        movers["abs_yoy"] = movers["yoy_pct"].abs()
        mv = movers.sort_values("abs_yoy", ascending=False).iloc[0]
        direction = "rose" if mv["yoy_pct"] > 0 else "fell"
        out.append(Insight(
            headline=(f"Biggest year-on-year move: {mv['metric_name']} {direction} "
                      f"{abs(mv['yoy_pct']):.1f}% to "
                      f"{data.num(mv['abhi_value'], 2)} {mv['metric_unit']}"),
            detail=(f"Measured in {mv['financial_year']}. "
                    + (f"Five-year CAGR {mv['cagr_pct']:.1f}%."
                       if pd.notna(mv["cagr_pct"]) else
                       "No CAGR available — the series crosses zero or starts negative.")),
            severity="opportunity" if mv["yoy_pct"] > 0 else "risk",
            evidence=movers.sort_values("abs_yoy", ascending=False)[
                ["metric_name", "financial_year", "abhi_value", "yoy_pct", "cagr_pct"]],
            source="metric_rank_summary"))

    return out


# ---------------------------------------------------------------------------
# 6. Benefits the market carries that ABHI does not
# ---------------------------------------------------------------------------

def feature_gaps(store=None) -> list[Insight]:
    """Gaps weighted by how widely rivals carry the benefit."""
    fg = _store(store)["vw_feature_gaps"]
    if fg.empty:
        return []

    gaps = fg[(fg["abhi_has"] == 0) | (fg["gap_status"].str.contains("Gap", na=False))]
    gaps = gaps.sort_values("rival_adoption_pct", ascending=False)

    if gaps.empty:
        return [Insight(
            headline=f"No benefit gaps — ABHI carries all {len(fg)} compared features",
            detail=("Every feature in the comparison is at parity with the rivals "
                    "that describe it."),
            severity="neutral", evidence=fg, source="feature_gaps")]

    top = gaps.iloc[0]
    out = [Insight(
        headline=(f"{len(gaps)} benefit gap(s) — widest is {top['feature_name']}, "
                  f"carried by {int(top['rivals_with'])} of "
                  f"{int(top['rivals_total'])} rivals ({top['rival_adoption_pct']:.0f}%)"),
        detail=("Gaps by rival adoption: "
                + "; ".join(f"{r['feature_name']} {r['rival_adoption_pct']:.0f}%"
                            for _, r in gaps.iterrows())
                + ". Adoption is measured from brochure text, not policy wording."),
        severity="risk",
        evidence=gaps[["feature_name", "abhi_has", "rivals_with", "rivals_total",
                       "rival_adoption_pct", "gap_status"]],
        source="feature_gaps")]

    parity = fg[~fg.index.isin(gaps.index)]
    if not parity.empty:
        out.append(Insight(
            headline=f"ABHI is at parity on the other {len(parity)} compared benefits",
            detail=("Including "
                    + ", ".join(parity.nlargest(4, "rival_adoption_pct")["feature_name"])
                    + "."),
            severity="neutral", evidence=parity, source="feature_gaps"))

    return out


# ---------------------------------------------------------------------------
# 7a. Premium rows that cannot be real
# ---------------------------------------------------------------------------

def premium_outliers(store=None, floor_ratio: float = 0.25) -> list[Insight]:
    """Rate rows far below their own slab's median — parsing damage, not pricing.

    A real rate chart rises monotonically with age, so within one
    (insurer, cover, tier, composition) group no row should sit at a small
    fraction of the group median. Rows below `floor_ratio` of it are flagged.

    The ratio is deliberate rather than an absolute rupee cut-off: premium per
    lakh legitimately falls a long way at high cover (Tata AIG's 3 Cr rows run
    to Rs 62 per lakh and are genuine), so an absolute floor would condemn real
    pricing. A within-group ratio only fires when an insurer's own curve breaks.
    """
    prem = _store(store)["vw_premium"]
    if prem.empty or "premium_amount" not in prem.columns:
        return []

    keys = [k for k in ["company_name", "sum_insured", "city_tier", "composition"]
            if k in prem.columns]
    df = prem.copy()
    df["group_median"] = df.groupby(keys, observed=True)["premium_amount"].transform("median")
    df["pct_of_median"] = df["premium_amount"] / df["group_median"]
    bad = df[df["pct_of_median"] < floor_ratio]
    if bad.empty:
        return []

    per_co = (bad.groupby("company_name", observed=True)
              .agg(bad_rows=("premium_amount", "size"),
                   lowest=("premium_amount", "min"),
                   slabs=("si_label", "nunique"),
                   min_age=("age", "min"),
                   max_age=("age", "max"))
              .reset_index()
              .sort_values("bad_rows", ascending=False))
    totals = (prem.groupby("company_name", observed=True).size()
              .rename("total_rows").reset_index())
    per_co = per_co.merge(totals, on="company_name", how="left")
    per_co["share_pct"] = (per_co["bad_rows"] / per_co["total_rows"] * 100).round(1)

    worst = per_co.iloc[0]
    example = bad[bad["company_name"] == worst["company_name"]].nsmallest(1, "premium_amount").iloc[0]

    return [Insight(
        headline=(f"{int(per_co['bad_rows'].sum())} premium rows are implausibly low "
                  f"and look like extraction damage — "
                  f"{worst['share_pct']:.0f}% of {worst['company_name']}'s rate table"),
        detail=(f"Worst example: {worst['company_name']} at "
                f"{data.cover(example['sum_insured'])} cover, age "
                f"{int(example['age'])}, priced {data.inr(example['premium_amount'])} "
                f"against a median of {data.inr(example['group_median'])} for that same "
                f"slab. Affected rows span ages {int(worst['min_age'])}–"
                f"{int(worst['max_age'])} across {int(worst['slabs'])} cover slabs. "
                f"These feed market_min and market_avg, so any segment they touch "
                f"understates the market and overstates ABHI's index."),
        severity="risk",
        evidence=per_co[["company_name", "bad_rows", "total_rows", "share_pct",
                         "slabs", "lowest", "min_age", "max_age"]],
        source="premium_outliers")]


# ---------------------------------------------------------------------------
# 7. What the data cannot support
# ---------------------------------------------------------------------------

def data_reliability_warnings(store=None, min_years: int = 3) -> list[Insight]:
    """Thin comparisons, absent insurers and short metric histories.

    These are surfaced deliberately. Every one of them is a place where a
    confident-looking number on another page is resting on very little.
    """
    s = _store(store)
    out = []

    # thin price segments
    avm = s["vw_abhi_vs_market"]
    thin = avm[avm["competitor_count"] < MIN_COMPETITORS].copy()
    if not thin.empty:
        thin = thin.sort_values(["competitor_count", "age_band"])
        out.append(Insight(
            headline=(f"{len(thin)} of {len(avm)} price segments compare against fewer "
                      f"than {MIN_COMPETITORS} competitors"),
            detail=(f"Thinnest is {int(thin['competitor_count'].min())} competitor(s). "
                    f"A 'market average' over one rival is that rival's price. These "
                    f"segments are shown greyed on the heatmap and excluded from every "
                    f"headline price figure."),
            severity="risk",
            evidence=thin[["age_band", "si_label", "competitor_count",
                           "abhi_premium", "market_avg", "price_index"]],
            source="data_reliability_warnings"))

    # insurers with no premium data / explicit caveats
    dq = s["vw_data_quality"]
    if not dq.empty:
        no_rows = dq[dq["premium_rows"].fillna(0) == 0]
        if not no_rows.empty:
            out.append(Insight(
                headline=(f"{len(no_rows)} insurer(s) contribute no premium data at all: "
                          f"{', '.join(no_rows['company_name'])}"),
                detail=("They appear in the company list but hold zero rate rows, so "
                        "they are absent from every price comparison on this dashboard."),
                severity="risk", evidence=no_rows, source="data_reliability_warnings"))

        caveats = dq[dq["caveat"].notna() & (dq["caveat"].str.upper() != "OK")]
        caveats = caveats[~caveats["company_name"].isin(no_rows["company_name"])]
        if not caveats.empty:
            out.append(Insight(
                headline=(f"{len(caveats)} insurer(s) carry an extraction caveat"),
                detail="; ".join(f"{r['company_name']}: {r['caveat']}"
                                 for _, r in caveats.iterrows()) + ".",
                severity="risk", evidence=caveats, source="data_reliability_warnings"))

    # metrics with too little history
    ml = s["vw_metrics_long"]
    if not ml.empty:
        cov = (ml.groupby("metric_name", observed=True)
               .agg(years=("financial_year", "nunique"),
                    companies=("company_name", "nunique"))
               .reset_index()
               .sort_values("years"))
        short = cov[cov["years"] < min_years]
        if not short.empty:
            out.append(Insight(
                headline=(f"{len(short)} metric(s) hold fewer than {min_years} years of "
                          f"history: {', '.join(short['metric_name'])}"),
                detail=("Trend and CAGR readings on those metrics are not meaningful. "
                        + "; ".join(f"{r['metric_name']}: {int(r['years'])} year(s) "
                                    f"across {int(r['companies'])} insurer(s)"
                                    for _, r in short.iterrows()) + "."),
                severity="risk", evidence=cov, source="data_reliability_warnings"))

    # per-insurer metric coverage holes
    mc = s["vw_metric_coverage"]
    if not mc.empty and "gwp_years" in mc.columns:
        holes = mc[(mc["gwp_years"].fillna(0) == 0) | (mc["roe_years"].fillna(0) == 0)]
        if not holes.empty:
            bits = []
            for _, r in holes.iterrows():
                missing = []
                if not r["gwp_years"]:
                    missing.append("GWP")
                if not r["roe_years"]:
                    missing.append("ROE")
                bits.append(f"{r['company_name']} (no {', '.join(missing)})")
            out.append(Insight(
                headline=(f"{len(holes)} insurer(s) are missing a headline financial "
                          f"series entirely"),
                detail="; ".join(bits) + ". Those insurers drop out of the affected "
                                         "trend charts rather than reading as zero.",
                severity="risk", evidence=mc, source="data_reliability_warnings"))

    return out


# ---------------------------------------------------------------------------
# Aggregation helpers used by the pages
# ---------------------------------------------------------------------------

ALL_FUNCTIONS = [
    price_position_by_age,
    slab_coverage_gap,
    widest_gaps,
    rival_threat_ranking,
    metric_rank_summary,
    feature_gaps,
    premium_outliers,
    data_reliability_warnings,
]


def all_insights(store=None) -> list[Insight]:
    out = []
    for fn in ALL_FUNCTIONS:
        try:
            out.extend(fn(store))
        except Exception as exc:  # a broken finding must not take the page down
            out.append(Insight(
                headline=f"{fn.__name__} could not be computed",
                detail=f"{type(exc).__name__}: {exc}",
                severity="risk", source=fn.__name__))
    return out


def highest_severity(insights: list[Insight], n: int = 3) -> list[Insight]:
    """Risks first, then opportunities, then neutral — stable within a tier."""
    return sorted(insights, key=lambda i: SEVERITY_ORDER.get(i.severity, 9))[:n]
