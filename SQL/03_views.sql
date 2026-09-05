/*  Analysis views
    Created in dependency order. This layer holds the competitive-intelligence logic: price indexing, peer ranking, growth/CAGR and the data-quality checks.

    Run the sql/ files in numeric order against your target database — select
    it first in SSMS, or pass it in the connection string. These scripts
    deliberately contain no USE statement so they cannot redirect themselves.

    Afterwards, populate the fact tables with the Python pipeline:
        python Python/extract_products.py     seeds PRODUCT_MASTER
        python Python/run_all.py              PDFs -> raw -> clean -> PREMIUM
*/

IF OBJECT_ID('business.vw_metrics_long', 'V') IS NOT NULL DROP VIEW [business].[vw_metrics_long];
GO
-- =====================================================================

-- 1. Long-format metrics — one row per company / year / metric.

--    Power BI slices far better off this than off 12 wide columns.

-- =====================================================================

CREATE   VIEW business.vw_metrics_long AS

SELECT

    c.company_id,

    c.company_name,

    CASE WHEN c.company_name = 'ABHI' THEN 1 ELSE 0 END AS is_focal,

    CASE WHEN c.company_name = 'ABHI' THEN 'ABHI' ELSE 'Peer' END AS company_role,

    m.financial_year,

    -- FY25 -> 2025, so charts sort chronologically instead of by string

    2000 + TRY_CAST(RIGHT(m.financial_year, 2) AS INT) AS fy_number,

    v.metric_name,

    v.metric_value,

    v.metric_group,

    v.metric_unit,

    v.higher_is_better

FROM business.company_metrics m

JOIN business.company_master c ON c.company_id = m.company_id

CROSS APPLY (VALUES

    ('GWP',            m.gwp,            'Scale',        'Rs Cr', 1),

    ('GDPI',           m.gdpi,           'Scale',        'Rs Cr', 1),

    ('Net Worth',      m.net_worth,      'Scale',        'Rs Cr', 1),

    ('AUM',            m.aum,            'Scale',        'Rs Cr', 1),

    ('Market Share',   m.market_share,   'Position',     '%',     1),

    ('ROE',            m.roe,            'Returns',      '%',     1),

    ('ROA',            m.roa,            'Returns',      '%',     1),

    ('Solvency Ratio', m.solvency_ratio, 'Strength',     'x',     1),

    ('Combined Ratio', m.combined_ratio, 'Underwriting', '%',     0),

    ('ICR',            m.icr,            'Underwriting', '%',     0),

    ('CSR',            m.csr,            'Service',      '%',     1)

) AS v(metric_name, metric_value, metric_group, metric_unit, higher_is_better)

WHERE v.metric_value IS NOT NULL;
GO

IF OBJECT_ID('business.vw_metric_rank', 'V') IS NOT NULL DROP VIEW [business].[vw_metric_rank];
GO
-- =====================================================================

-- 6. Where ABHI ranks — the competitive answer, per metric per year.

--    Ranking respects direction: a LOW combined ratio is good.

-- =====================================================================

CREATE   VIEW business.vw_metric_rank AS

WITH ranked AS (

    SELECT

        company_id, company_name, is_focal, financial_year, fy_number,

        metric_name, metric_group, metric_unit, metric_value, higher_is_better,

        CASE WHEN higher_is_better = 1

             THEN RANK() OVER (PARTITION BY metric_name, fy_number

                               ORDER BY metric_value DESC)

             ELSE RANK() OVER (PARTITION BY metric_name, fy_number

                               ORDER BY metric_value ASC)

        END AS rank_position,

        COUNT(*) OVER (PARTITION BY metric_name, fy_number) AS peer_count,

        AVG(metric_value) OVER (PARTITION BY metric_name, fy_number) AS peer_avg,

        MAX(metric_value) OVER (PARTITION BY metric_name, fy_number) AS peer_max,

        MIN(metric_value) OVER (PARTITION BY metric_name, fy_number) AS peer_min

    FROM business.vw_metrics_long

)

SELECT *,

    CAST(metric_value * 100.0 / NULLIF(peer_avg, 0) AS DECIMAL(10,2)) AS vs_peer_avg,

    CASE

        WHEN rank_position = 1 THEN 'Leader'

        WHEN rank_position <= CEILING(peer_count / 3.0) THEN 'Top third'

        WHEN rank_position <= CEILING(peer_count * 2 / 3.0) THEN 'Middle third'

        ELSE 'Bottom third'

    END AS rank_band

FROM ranked;
GO

IF OBJECT_ID('business.vw_metrics_cagr', 'V') IS NOT NULL DROP VIEW [business].[vw_metrics_cagr];
GO
-- =====================================================================

-- 5. CAGR across the full window held for each company

-- =====================================================================

CREATE   VIEW business.vw_metrics_cagr AS

WITH bounds AS (

    SELECT company_id, company_name, is_focal, metric_name, metric_group,

           MIN(fy_number) AS first_fy,

           MAX(fy_number) AS last_fy

    FROM business.vw_metrics_long

    GROUP BY company_id, company_name, is_focal, metric_name, metric_group

    HAVING COUNT(*) >= 3

),

vals AS (

    SELECT b.*,

           f.metric_value AS first_value,

           l.metric_value AS last_value

    FROM bounds b

    JOIN business.vw_metrics_long f

      ON f.company_id = b.company_id AND f.metric_name = b.metric_name

     AND f.fy_number = b.first_fy

    JOIN business.vw_metrics_long l

      ON l.company_id = b.company_id AND l.metric_name = b.metric_name

     AND l.fy_number = b.last_fy

)

SELECT

    company_id, company_name, is_focal, metric_name, metric_group,

    first_fy, last_fy, first_value, last_value,

    last_fy - first_fy AS years,

    CASE

        WHEN first_value > 0 AND last_value > 0 AND last_fy > first_fy

        THEN CAST((POWER(last_value / first_value,

                         1.0 / (last_fy - first_fy)) - 1) * 100

                  AS DECIMAL(10,2))

        ELSE NULL

    END AS cagr_pct

FROM vals;
GO

IF OBJECT_ID('business.vw_metrics_growth', 'V') IS NOT NULL DROP VIEW [business].[vw_metrics_growth];
GO
-- =====================================================================

-- 4. Year-on-year growth, per company per metric

-- =====================================================================

CREATE   VIEW business.vw_metrics_growth AS

WITH seq AS (

    SELECT company_id, company_name, is_focal, company_role,

           metric_name, metric_group, metric_unit, higher_is_better,

           financial_year, fy_number, metric_value,

           LAG(metric_value) OVER (PARTITION BY company_id, metric_name

                                   ORDER BY fy_number) AS prev_value,

           FIRST_VALUE(metric_value) OVER (PARTITION BY company_id, metric_name

                                           ORDER BY fy_number) AS base_value,

           MIN(fy_number) OVER (PARTITION BY company_id, metric_name) AS base_fy

    FROM business.vw_metrics_long

)

SELECT

    company_id, company_name, is_focal, company_role,

    metric_name, metric_group, metric_unit, higher_is_better,

    financial_year, fy_number, metric_value, prev_value,

    metric_value - prev_value                                AS yoy_change,

    CAST((metric_value - prev_value) * 100.0

         / NULLIF(ABS(prev_value), 0) AS DECIMAL(10,2))      AS yoy_pct,

    -- indexed to the first available year, for shared-axis trend charts

    CAST(metric_value * 100.0

         / NULLIF(base_value, 0) AS DECIMAL(10,2))           AS indexed_to_base,

    base_fy

FROM seq;
GO

IF OBJECT_ID('business.vw_abhi_scorecard', 'V') IS NOT NULL DROP VIEW [business].[vw_abhi_scorecard];
GO
-- =====================================================================

-- 7. ABHI scorecard — one row per metric, latest year, with context

-- =====================================================================

CREATE   VIEW business.vw_abhi_scorecard AS

SELECT

    r.metric_name,

    r.metric_group,

    r.metric_unit,

    r.financial_year,

    r.metric_value           AS abhi_value,

    r.rank_position,

    r.peer_count,

    r.peer_avg,

    r.peer_min,

    r.peer_max,

    r.vs_peer_avg,

    r.rank_band,

    g.yoy_pct,

    cg.cagr_pct

FROM business.vw_metric_rank r

LEFT JOIN business.vw_metrics_growth g

       ON g.company_id = r.company_id

      AND g.metric_name = r.metric_name

      AND g.fy_number = r.fy_number

LEFT JOIN business.vw_metrics_cagr cg

       ON cg.company_id = r.company_id

      AND cg.metric_name = r.metric_name

WHERE r.is_focal = 1

  AND r.fy_number = (SELECT MAX(fy_number) FROM business.vw_metrics_long

                      WHERE is_focal = 1);
GO

IF OBJECT_ID('business.vw_dim_product', 'V') IS NOT NULL DROP VIEW [business].[vw_dim_product];
GO
-- =====================================================================

-- 1. Product dimension, with the focal-company flag

-- =====================================================================

CREATE   VIEW business.vw_dim_product AS

SELECT

    p.product_id,

    c.company_id,

    c.company_name,

    p.product_name,

    c.company_name + ' — ' + p.product_name  AS product_label,

    CASE WHEN c.company_name = 'ABHI' THEN 1 ELSE 0 END AS is_focal,

    CASE WHEN c.company_name = 'ABHI' THEN 'ABHI' ELSE 'Competitor' END AS company_role

FROM business.PRODUCT_MASTER p

JOIN business.COMPANY_MASTER c ON c.company_id = p.company_id;
GO

IF OBJECT_ID('business.vw_premium', 'V') IS NOT NULL DROP VIEW [business].[vw_premium];
GO
CREATE   VIEW business.vw_premium AS

SELECT

    pr.premium_id,

    pr.product_id,

    d.company_name,

    d.product_name,

    d.product_label,

    d.is_focal,

    d.company_role,

    pr.age,

    CASE

        WHEN pr.age < 18 THEN '00-17'

        WHEN pr.age < 26 THEN '18-25'

        WHEN pr.age < 36 THEN '26-35'

        WHEN pr.age < 46 THEN '36-45'

        WHEN pr.age < 56 THEN '46-55'

        WHEN pr.age < 66 THEN '56-65'

        ELSE '66+'

    END                                       AS age_band,

    pr.sum_insured,

    CAST(pr.sum_insured / 100000 AS INT)      AS si_lakhs,

    -- cast to INT before building the string: sum_insured is numeric with

    -- decimals, so the division yields 5.000000 and overflows VARCHAR(10)

    CASE

        WHEN pr.sum_insured >= 10000000

            THEN CAST(CAST(pr.sum_insured / 10000000 AS INT) AS VARCHAR(12)) + ' Cr'

        ELSE CAST(CAST(pr.sum_insured / 100000 AS INT) AS VARCHAR(12)) + ' L'

    END                                       AS si_label,

    pr.premium_amount,

    pr.family_type,

    pr.adults,

    pr.children,

    CAST(pr.adults AS VARCHAR(2)) + 'A+' +

    CAST(pr.children AS VARCHAR(2)) + 'C'     AS composition,

    pr.city_tier,

    pr.policy_term,

    CAST(pr.premium_amount * 100000.0 / NULLIF(pr.sum_insured, 0)

         AS DECIMAL(12,2))                    AS premium_per_lakh

FROM business.PREMIUM pr

JOIN business.vw_dim_product d ON d.product_id = pr.product_id;
GO

IF OBJECT_ID('business.vw_price_grid', 'V') IS NOT NULL DROP VIEW [business].[vw_price_grid];
GO
-- =====================================================================

-- 4. Like-for-like grid: one row per (age band, slab) per company

--    Restricted to Tier 1 individual cover, the only basis where every

--    company has data.

-- =====================================================================

CREATE   VIEW business.vw_price_grid AS

SELECT

    company_name,

    product_name,

    product_label,

    is_focal,

    company_role,

    age_band,

    si_label,

    sum_insured,

    COUNT(*)                              AS points,

    CAST(AVG(premium_amount) AS INT)      AS avg_premium,

    MIN(premium_amount)                   AS min_premium,

    MAX(premium_amount)                   AS max_premium,

    CAST(AVG(premium_per_lakh) AS DECIMAL(12,2)) AS avg_premium_per_lakh

FROM business.vw_premium

WHERE city_tier = 'Tier 1'

  AND adults = 1 AND children = 0

GROUP BY company_name, product_name, product_label, is_focal, company_role,

         age_band, si_label, sum_insured;
GO

IF OBJECT_ID('business.vw_abhi_vs_market', 'V') IS NOT NULL DROP VIEW [business].[vw_abhi_vs_market];
GO
-- =====================================================================

-- 5. ABHI vs market — the core competitive view

--    Only cells where ABHI actually has a price are returned, so the

--    index never compares ABHI against nothing.

-- =====================================================================

CREATE   VIEW business.vw_abhi_vs_market AS

WITH abhi AS (

    SELECT age_band, sum_insured, si_label, avg_premium AS abhi_premium

    FROM business.vw_price_grid

    WHERE is_focal = 1

),

market AS (

    SELECT age_band, sum_insured,

           CAST(AVG(avg_premium) AS INT) AS market_avg,

           MIN(avg_premium)              AS market_min,

           MAX(avg_premium)              AS market_max,

           COUNT(*)                      AS competitor_count

    FROM business.vw_price_grid

    WHERE is_focal = 0

    GROUP BY age_band, sum_insured

)

SELECT

    a.age_band,

    a.si_label,

    a.sum_insured,

    a.abhi_premium,

    m.market_avg,

    m.market_min,

    m.market_max,

    m.competitor_count,

    a.abhi_premium - m.market_avg                             AS gap_rupees,

    CAST(a.abhi_premium * 100.0 / NULLIF(m.market_avg, 0)

         AS DECIMAL(6,1))                                     AS price_index,

    CASE

        WHEN a.abhi_premium * 1.0 / NULLIF(m.market_avg,0) > 1.15 THEN 'Premium priced'

        WHEN a.abhi_premium * 1.0 / NULLIF(m.market_avg,0) > 1.05 THEN 'Above market'

        WHEN a.abhi_premium * 1.0 / NULLIF(m.market_avg,0) > 0.95 THEN 'At market'

        WHEN a.abhi_premium * 1.0 / NULLIF(m.market_avg,0) > 0.85 THEN 'Below market'

        ELSE 'Aggressively priced'

    END                                                       AS position,

    CASE WHEN a.abhi_premium <= m.market_min THEN 1 ELSE 0 END AS is_cheapest,

    CASE WHEN a.abhi_premium >= m.market_max THEN 1 ELSE 0 END AS is_dearest

FROM abhi a

JOIN market m

  ON m.age_band = a.age_band AND m.sum_insured = a.sum_insured;
GO

IF OBJECT_ID('business.vw_data_quality', 'V') IS NOT NULL DROP VIEW [business].[vw_data_quality];
GO
-- =====================================================================

-- 10. Data quality — put this on the dashboard, do not hide it

-- =====================================================================

CREATE   VIEW business.vw_data_quality AS

SELECT

    d.company_name,

    d.product_name,

    (SELECT COUNT(*) FROM business.PREMIUM x

      WHERE x.product_id = d.product_id)              AS premium_rows,

    (SELECT COUNT(DISTINCT x.sum_insured) FROM business.PREMIUM x

      WHERE x.product_id = d.product_id)              AS slabs,

    (SELECT COUNT(DISTINCT x.city_tier) FROM business.PREMIUM x

      WHERE x.product_id = d.product_id)              AS tiers,

    CASE WHEN EXISTS (SELECT 1 FROM business.HEALTH_FEATURES h

                       WHERE h.product_id = d.product_id)

         THEN 1 ELSE 0 END                            AS has_features,

    CASE

        WHEN d.company_name = 'ABHI'

            THEN 'Age curve unreliable — source chart interleaves two rate tables'

        WHEN NOT EXISTS (SELECT 1 FROM business.PREMIUM x

                          WHERE x.product_id = d.product_id)

            THEN 'No premium data'

        ELSE 'OK'

    END                                               AS caveat

FROM business.vw_dim_product d;
GO

IF OBJECT_ID('business.vw_feature_matrix', 'V') IS NOT NULL DROP VIEW [business].[vw_feature_matrix];
GO
-- =====================================================================

-- 7. Feature matrix, unpivoted so Power BI can slice by feature

-- =====================================================================

CREATE   VIEW business.vw_feature_matrix AS

SELECT

    d.company_name,

    d.product_name,

    d.product_label,

    d.is_focal,

    d.company_role,

    f.feature_name,

    f.has_feature,

    CASE f.has_feature WHEN 1 THEN 'Yes' ELSE 'No' END AS has_feature_label

FROM business.HEALTH_FEATURES h

JOIN business.vw_dim_product d ON d.product_id = h.product_id

CROSS APPLY (VALUES

    -- cast to int: the source columns are bit, and SQL Server will not

    -- SUM or AVG a bit

    ('OPD Cover',              CAST(h.opd_cover AS INT)),

    ('Maternity',              CAST(h.maternity_cover AS INT)),

    ('Restoration',            CAST(h.restoration AS INT)),

    ('No Claim Bonus',         CAST(h.ncb AS INT)),

    ('AYUSH',                  CAST(h.ayush_cover AS INT)),

    ('Day Care',               CAST(h.day_care AS INT)),

    ('Organ Donor',            CAST(h.organ_donor AS INT)),

    ('Domiciliary',            CAST(h.domiciliary_treatment AS INT)),

    ('Annual Health Checkup',  CAST(h.annual_health_checkup AS INT)),

    ('Consumables',            CAST(h.consumables_cover AS INT))

) AS f(feature_name, has_feature);
GO

IF OBJECT_ID('business.vw_feature_gaps', 'V') IS NOT NULL DROP VIEW [business].[vw_feature_gaps];
GO
-- =====================================================================

-- 8. Feature gaps — what rivals offer that ABHI does not

-- =====================================================================

CREATE   VIEW business.vw_feature_gaps AS

WITH abhi AS (

    SELECT feature_name, CAST(has_feature AS INT) AS abhi_has

    FROM business.vw_feature_matrix WHERE is_focal = 1

),

rivals AS (

    SELECT feature_name,

           SUM(CAST(has_feature AS INT)) AS rivals_with,

           COUNT(*)              AS rivals_total

    FROM business.vw_feature_matrix WHERE is_focal = 0

    GROUP BY feature_name

)

SELECT

    r.feature_name,

    a.abhi_has,

    r.rivals_with,

    r.rivals_total,

    CAST(r.rivals_with * 100.0 / NULLIF(r.rivals_total,0)

         AS DECIMAL(5,1))        AS rival_adoption_pct,

    CASE

        WHEN a.abhi_has = 0 AND r.rivals_with * 1.0 / NULLIF(r.rivals_total,0) >= 0.6

            THEN 'Gap — most rivals have it'

        WHEN a.abhi_has = 0 AND r.rivals_with > 0

            THEN 'Partial gap'

        WHEN a.abhi_has = 1 AND r.rivals_with * 1.0 / NULLIF(r.rivals_total,0) <= 0.4

            THEN 'Differentiator'

        ELSE 'Parity'

    END                          AS gap_status

FROM abhi a

JOIN rivals r ON r.feature_name = a.feature_name;
GO

IF OBJECT_ID('business.vw_head_to_head', 'V') IS NOT NULL DROP VIEW [business].[vw_head_to_head];
GO
-- =====================================================================

-- 6. Head-to-head: ABHI against one named rival, same cell

-- =====================================================================

CREATE   VIEW business.vw_head_to_head AS

SELECT

    r.company_name           AS rival,

    r.product_name           AS rival_product,

    a.age_band,

    a.si_label,

    a.sum_insured,

    a.avg_premium            AS abhi_premium,

    r.avg_premium            AS rival_premium,

    a.avg_premium - r.avg_premium AS gap_rupees,

    CAST(a.avg_premium * 100.0 / NULLIF(r.avg_premium, 0)

         AS DECIMAL(6,1))    AS index_vs_rival,

    CASE WHEN a.avg_premium < r.avg_premium THEN 'ABHI cheaper'

         WHEN a.avg_premium > r.avg_premium THEN 'Rival cheaper'

         ELSE 'Level' END    AS winner

FROM business.vw_price_grid a

JOIN business.vw_price_grid r

  ON r.age_band = a.age_band

 AND r.sum_insured = a.sum_insured

 AND r.is_focal = 0

WHERE a.is_focal = 1;
GO

IF OBJECT_ID('business.vw_metric_coverage', 'V') IS NOT NULL DROP VIEW [business].[vw_metric_coverage];
GO
-- =====================================================================

-- 8. Metric coverage — which company/year/metric cells actually exist.

--    Surface this: an empty cell in a peer matrix reads as a zero unless

--    the reader is told otherwise.

-- =====================================================================

CREATE   VIEW business.vw_metric_coverage AS

SELECT

    c.company_name,

    COUNT(DISTINCT m.financial_year)                         AS years_held,

    MIN(m.financial_year)                                    AS earliest,

    MAX(m.financial_year)                                    AS latest,

    SUM(CASE WHEN m.gwp IS NOT NULL THEN 1 ELSE 0 END)       AS gwp_years,

    SUM(CASE WHEN m.roe IS NOT NULL THEN 1 ELSE 0 END)       AS roe_years,

    SUM(CASE WHEN m.combined_ratio IS NOT NULL THEN 1 ELSE 0 END) AS cor_years,

    SUM(CASE WHEN m.market_share IS NOT NULL THEN 1 ELSE 0 END)   AS ms_years

FROM business.company_master c

LEFT JOIN business.company_metrics m ON m.company_id = c.company_id

GROUP BY c.company_name;
GO

IF OBJECT_ID('business.vw_metrics_latest', 'V') IS NOT NULL DROP VIEW [business].[vw_metrics_latest];
GO
-- =====================================================================

-- 2. Latest financial year available per company

--    (not every insurer has the same last year)

-- =====================================================================

CREATE   VIEW business.vw_metrics_latest AS

WITH ranked AS (

    SELECT *,

           ROW_NUMBER() OVER (PARTITION BY company_id, metric_name

                              ORDER BY fy_number DESC) AS rn

    FROM business.vw_metrics_long

)

SELECT company_id, company_name, is_focal, company_role,

       financial_year, fy_number,

       metric_name, metric_value, metric_group, metric_unit, higher_is_better

FROM ranked

WHERE rn = 1;
GO

IF OBJECT_ID('business.vw_peer_comparison', 'V') IS NOT NULL DROP VIEW [business].[vw_peer_comparison];
GO
-- =====================================================================

-- 3. Peer comparison matrix — the GenXAI headline table.

--    One row per insurer, latest year, metrics pivoted to columns.

-- =====================================================================

CREATE   VIEW business.vw_peer_comparison AS

SELECT

    c.company_name,

    CASE WHEN c.company_name = 'ABHI' THEN 1 ELSE 0 END AS is_focal,

    m.financial_year,

    m.gwp,

    m.gdpi,

    m.net_worth,

    m.aum,

    m.market_share,

    m.roe,

    m.roa,

    m.solvency_ratio,

    m.combined_ratio,

    m.icr,

    -- derived, and useful: how much premium each rupee of net worth carries

    CAST(m.gwp / NULLIF(m.net_worth, 0) AS DECIMAL(10,2)) AS gwp_to_net_worth,

    p.product_name,

    p.product_id

FROM business.company_metrics m

JOIN business.company_master c ON c.company_id = m.company_id

LEFT JOIN business.PRODUCT_MASTER p ON p.company_id = c.company_id

WHERE m.financial_year = (

    SELECT MAX(financial_year) FROM business.company_metrics x

    WHERE x.company_id = m.company_id

);
GO

IF OBJECT_ID('business.vw_policy_terms', 'V') IS NOT NULL DROP VIEW [business].[vw_policy_terms];
GO
-- =====================================================================

-- 9. Structural terms side by side (numeric, more reliable than flags)

-- =====================================================================

CREATE   VIEW business.vw_policy_terms AS

SELECT

    d.company_name,

    d.product_name,

    d.is_focal,

    d.company_role,

    h.waiting_period,

    TRY_CAST(REPLACE(h.waiting_period, ' Days', '') AS INT)  AS waiting_days,

    h.ped_waiting,

    TRY_CAST(REPLACE(h.ped_waiting, ' Years', '') AS INT)    AS ped_years,

    h.room_rent,

    h.pre_hospitalization,

    h.post_hospitalization,

    h.pre_hospitalization + h.post_hospitalization           AS total_hosp_days,

    h.ambulance_cover

FROM business.HEALTH_FEATURES h

JOIN business.vw_dim_product d ON d.product_id = h.product_id;
GO

IF OBJECT_ID('business.vw_slab_coverage', 'V') IS NOT NULL DROP VIEW [business].[vw_slab_coverage];
GO
-- =====================================================================

-- 3. Which slabs each company actually offers

--    ABHI's missing 5L entry point shows up here

-- =====================================================================

CREATE   VIEW business.vw_slab_coverage AS

SELECT

    company_name,

    product_name,

    si_label,

    sum_insured,

    COUNT(*)          AS rate_points,

    MIN(age)          AS min_age,

    MAX(age)          AS max_age,

    MIN(premium_amount) AS cheapest,

    MAX(premium_amount) AS dearest

FROM business.vw_premium

WHERE city_tier = 'Tier 1' AND adults = 1 AND children = 0

GROUP BY company_name, product_name, si_label, sum_insured;
GO
