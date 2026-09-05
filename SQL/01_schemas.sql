/*  Schemas
    raw -> clean -> business: the three pipeline stages.

    Run the sql/ files in numeric order against your target database — select
    it first in SSMS, or pass it in the connection string. These scripts
    deliberately contain no USE statement so they cannot redirect themselves.

    Afterwards, populate the fact tables with the Python pipeline:
        python Python/extract_products.py     seeds PRODUCT_MASTER
        python Python/run_all.py              PDFs -> raw -> clean -> PREMIUM
*/

IF SCHEMA_ID('business') IS NULL EXEC('CREATE SCHEMA business');
GO

IF SCHEMA_ID('clean') IS NULL EXEC('CREATE SCHEMA clean');
GO

IF SCHEMA_ID('raw') IS NULL EXEC('CREATE SCHEMA raw');
GO
