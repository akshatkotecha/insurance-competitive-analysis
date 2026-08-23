# Power BI build guide — insurance competitive intelligence

Everything tedious (data connection, DAX, color theme) is pre-written in this
folder. Building the report itself is mostly dragging fields onto a canvas.
Total time if you follow this in order: roughly 45–60 minutes for all four
pages, most of it on page 1 since that's where the conditional formatting
pattern gets set up once and then reused.

## 1. Connect (5 min)

Power BI Desktop → **Get Data → SQL Server**
- Server: `AKSHAT\SQLEXPRESS`
- Database: `INSURANCEDB`
- Data Connectivity mode: **Import**
- Leave credentials on Windows (matches how the Python apps connect)

In the Navigator, tick these five under the `business` schema and click
**Load**: `vw_abhi_vs_market`, `vw_data_quality`, `vw_peer_comparison`,
`vw_metrics_long`, `vw_premium`. (`power_query.m` in this folder has the
raw M if you want more control via Advanced Editor instead — not required,
the navigator checkboxes do the same thing.)

## 2. Apply the theme (1 min)

**View → Themes → Browse for themes** → select `theme.json` in this folder.
Dark background, the same 7-insurer color order used in the Python
dashboards (ABHI first, always blue), and good/neutral/bad colors wired to
`#0ca30c` / `#8a8a8a` / `#d03b3b` so any visual that supports Power BI's
built-in sentiment colors picks them up automatically.

The top-level colors (`dataColors`, `background`, `foreground`,
`good`/`neutral`/`bad`) are stable, well-documented schema fields and will
apply cleanly. The `visualStyles` section (per-visual borders, table row
striping, card font sizing) I wrote without a Power BI Desktop instance to
test against — Power BI generally ignores properties it doesn't recognize
rather than failing the import, but if the theme doesn't fully load or a
few visuals look unstyled, the color system is doing its job regardless;
just nudge borders/fonts by hand for whichever visual didn't pick it up.

## 3. Add the DAX measures (10 min)

Open `dax_measures.dax`. For each measure: select the table it's listed
under in the Fields pane → **Table tools → New measure** → paste → Enter.
The comments under each one say exactly which visual/field it plugs into —
that's step 4.

**Read the block comment at the top of the `vw_abhi_vs_market` section
before building page 1.** `competitor_count` ranges from 1 to 6 across the
47 rows — the entire 2 Cr column is compared against exactly one rival
(`competitor_count = 1`), and 75 L against only 3-4. A plain
`AVERAGE(price_index)` blends those thin, unreliable comparisons in at
full strength — it's 87.5 with them included vs. 90.8 restricted to
segments with 5+ competitors, and "segments where ABHI is cheapest" reads
14/47 vs. 7/36 — over a third of that "win count" is single-competitor
comparisons, not market wins. Use the `(Reliable)` measures on the
headline cards, not the plain averages.

## 4. Build the four pages

**Page 1 — Position**
- 4 Card visuals: `Avg Price Index (Reliable)`, `Segments Below Market %
  (Reliable)`, `Segments Above Market % (Reliable)`, `Avg Premium Gap`. Add
  a small caption/tooltip on each disclosing the all-segment number (e.g.
  `Avg Price Index (All Segments)` and `Thin Segment Count`) rather than
  just showing the clean restricted number with no acknowledgment that
  segments were excluded.
- 1 Matrix visual: Rows = `age_band`, Columns = `si_label`, Values =
  `Price Index Label` (**not** raw `price_index` — this measure appends
  "(n=…)" onto thin cells so the sample size is visible without hovering)
  → Format → Cell elements → Background color → Conditional formatting →
  Field value → `Price Index Cell Color`. Thin cells (competitor_count <
  5) flatten to neutral grey instead of green/red — see the comment on
  that measure for why a semi-transparent "wash" (what the Streamlit
  heatmap does) isn't reproducible in a Power BI Matrix.
- A few Card or Multi-row Card visuals off `vw_data_quality` for the
  coverage strip, using `Coverage Status Color` for the status text.

**Page 2 — Peer comparison**
- 1 Table visual on `vw_peer_comparison` with the metric columns → Format →
  Cell elements → row background → Conditional formatting → Field value →
  `Is Focal Row Color`. ABHI's row lights up automatically.

**Page 3 — Trends**
- 1 Line chart: Axis = `financial_year`, Legend = `company_name`, Values =
  `metric_value`.
- 1 Slicer on `metric_name`, default selection "GWP". That slicer *is* the
  dropdown from the Python version — no extra work.

**Page 4 — Pricing detail**
- 1 Line chart: Axis = `Cover Label` (the calculated column from
  `dax_measures.dax`, sorted by `sum_insured` — not the view's own
  `si_label`, which collides two different cover amounts into one label;
  see the comment there), Legend = `company_name`, Values =
  `Median Premium Per Lakh`.
- 1 Bar chart: Axis = `company_name`, Values = `Selected Premium`, sorted
  descending.
- 4 Slicers on the same page: `age`, `sum_insured`, `city_tier`,
  `composition`. Power BI cross-filters the bar chart the instant you add
  these — this is the "pick an age and an amount, see it for every
  insurer" feature you asked for, and it's free once the slicers exist.

## What doesn't come across from the Dash app

The **Ask** tab (the SQL chatbot) has no Power BI equivalent — Power BI
visuals don't run arbitrary Python routing logic against free-text input.
If you want that capability alongside the Power BI report, keep
`dash_app.py` running for that one piece, or leave it out of the Power BI
version entirely.

## If you want dark AND light

`theme.json` here is one deliberately-designed dark theme (matches what you
liked in the Dash screenshots). Power BI doesn't have a built-in
viewer-facing light/dark toggle the way a web app does — a second theme
would need a duplicate report page set + bookmark switching, which is a
real chunk of extra work for a "nice to have." Say the word if you want
that built out too; otherwise ship the dark one.
