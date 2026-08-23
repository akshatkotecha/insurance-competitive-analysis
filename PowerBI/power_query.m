// Power BI Desktop → Home → Get Data → SQL Server
//   Server:   AKSHAT\SQLEXPRESS
//   Database: INSURANCEDB
//   Data Connectivity mode: Import
//   Windows authentication (same as the Python apps' Trusted_Connection=yes —
//   no username/password to enter)
//
// You'll get a navigator dialog. Either tick the 5 business.vw_* views
// directly (fastest — skip everything below), OR for more control /
// query folding, create 5 Blank Queries and paste one block each into
// Home → Advanced Editor. Rename each query to match the name in the
// comment so the DAX measures below resolve without edits.

// ============================================================
// Query name: vw_abhi_vs_market   (Position tab — heatmap + KPIs)
// ============================================================
let
    Source = Sql.Database("AKSHAT\SQLEXPRESS", "INSURANCEDB"),
    Data = Source{[Schema = "business", Item = "vw_abhi_vs_market"]}[Data]
in
    Data

// ============================================================
// Query name: vw_data_quality   (Position tab — coverage strip)
// ============================================================
let
    Source = Sql.Database("AKSHAT\SQLEXPRESS", "INSURANCEDB"),
    Data = Source{[Schema = "business", Item = "vw_data_quality"]}[Data]
in
    Data

// ============================================================
// Query name: vw_peer_comparison   (Peer comparison tab)
// ============================================================
let
    Source = Sql.Database("AKSHAT\SQLEXPRESS", "INSURANCEDB"),
    Data = Source{[Schema = "business", Item = "vw_peer_comparison"]}[Data]
in
    Data

// ============================================================
// Query name: vw_metrics_long   (Trends tab — already long/tidy,
// perfect for a Power BI line chart: slice by metric_name, plot
// metric_value by financial_year, color by company_name)
// ============================================================
let
    Source = Sql.Database("AKSHAT\SQLEXPRESS", "INSURANCEDB"),
    Data = Source{[Schema = "business", Item = "vw_metrics_long"]}[Data]
in
    Data

// ============================================================
// Query name: vw_premium   (Pricing detail tab — the big one,
// ~8.5k rows; Import mode handles this easily)
// ============================================================
let
    Source = Sql.Database("AKSHAT\SQLEXPRESS", "INSURANCEDB"),
    Data = Source{[Schema = "business", Item = "vw_premium"]}[Data]
in
    Data

// ------------------------------------------------------------
// After loading all 5: Home → Manage Relationships. These views
// don't need explicit relationships for the pages below — each
// page's visuals pull from one view at a time — but if you later
// want cross-page slicers, relate them on company_name.
// ------------------------------------------------------------
