/*  Base tables
    COMPANY_MASTER -> PRODUCT_MASTER -> PREMIUM / HEALTH_FEATURES; COMPANY_METRICS hangs off the company.

    Run the sql/ files in numeric order against your target database — select
    it first in SSMS, or pass it in the connection string. These scripts
    deliberately contain no USE statement so they cannot redirect themselves.

    Afterwards, populate the fact tables with the Python pipeline:
        python Python/extract_products.py     seeds PRODUCT_MASTER
        python Python/run_all.py              PDFs -> raw -> clean -> PREMIUM
*/

IF OBJECT_ID('business.COMPANY_MASTER') IS NULL
CREATE TABLE [business].[COMPANY_MASTER] (
    [company_id] int IDENTITY(1,1) NOT NULL,
    [company_name] varchar(100) NULL,
    [website] varchar(200) NULL,
    [headquarters] varchar(100) NULL,
    CONSTRAINT [PK_COMPANY_MASTER] PRIMARY KEY ([company_id])
);
GO

IF OBJECT_ID('business.PRODUCT_MASTER') IS NULL
CREATE TABLE [business].[PRODUCT_MASTER] (
    [product_id] int IDENTITY(1,1) NOT NULL,
    [company_id] int NOT NULL,
    [product_name] varchar(200) NULL,
    [insurance_type] varchar(100) NULL,
    [category] varchar(100) NULL,
    CONSTRAINT [PK_PRODUCT_MASTER] PRIMARY KEY ([product_id])
);
GO

IF OBJECT_ID('business.COMPANY_METRICS') IS NULL
CREATE TABLE [business].[COMPANY_METRICS] (
    [metric_id] int IDENTITY(1,1) NOT NULL,
    [company_id] int NULL,
    [financial_year] varchar(20) NULL,
    [gwp] decimal(18,2) NULL,
    [gdpi] decimal(18,2) NULL,
    [csr] decimal(10,2) NULL,
    [icr] decimal(10,2) NULL,
    [roe] decimal(10,2) NULL,
    [roa] decimal(10,2) NULL,
    [solvency_ratio] decimal(10,2) NULL,
    [market_share] decimal(10,2) NULL,
    [net_worth] decimal(18,2) NULL,
    [aum] decimal(18,2) NULL,
    [combined_ratio] decimal(10,2) NULL,
    [claim_turnaround_time] decimal(10,2) NULL,
    CONSTRAINT [PK_COMPANY_METRICS] PRIMARY KEY ([metric_id])
);
GO

IF OBJECT_ID('business.HEALTH_FEATURES') IS NULL
CREATE TABLE [business].[HEALTH_FEATURES] (
    [feature_id] int IDENTITY(1,1) NOT NULL,
    [product_id] int NULL,
    [waiting_period] varchar(100) NULL,
    [ped_waiting] varchar(100) NULL,
    [room_rent] varchar(100) NULL,
    [opd_cover] bit NULL,
    [maternity_cover] bit NULL,
    [restoration] bit NULL,
    [ncb] bit NULL,
    [ayush_cover] bit NULL,
    [pre_hospitalization] int NULL,
    [post_hospitalization] int NULL,
    [day_care] bit NULL,
    [organ_donor] bit NULL,
    [domiciliary_treatment] bit NULL,
    [annual_health_checkup] bit NULL,
    [ambulance_cover] int NULL,
    [consumables_cover] bit NULL,
    CONSTRAINT [PK_HEALTH_FEATURES] PRIMARY KEY ([feature_id])
);
GO

IF OBJECT_ID('business.PREMIUM') IS NULL
CREATE TABLE [business].[PREMIUM] (
    [premium_id] int IDENTITY(1,1) NOT NULL,
    [product_id] int NULL,
    [age] int NULL,
    [family_type] varchar(50) NULL,
    [sum_insured] decimal(15,2) NULL,
    [premium_amount] decimal(15,2) NULL,
    [adults] int NULL,
    [children] int NULL,
    [city_tier] varchar(50) NULL,
    [policy_term] int NULL,
    CONSTRAINT [PK_PREMIUM] PRIMARY KEY ([premium_id])
);
GO

IF OBJECT_ID('raw.PDF_TEXT_RAW') IS NULL
CREATE TABLE [raw].[PDF_TEXT_RAW] (
    [pdf_id] int IDENTITY(1,1) NOT NULL,
    [company_name] varchar(100) NOT NULL,
    [product_name] varchar(200) NULL,
    [document_type] varchar(50) NULL,
    [page_number] int NOT NULL,
    [raw_text] nvarchar(MAX) NULL,
    [extracted_on] datetime NULL,
    [company_id] int NOT NULL,
    CONSTRAINT [PK_PDF_TEXT_RAW] PRIMARY KEY ([pdf_id])
);
GO

IF OBJECT_ID('clean.PDF_TEXT_CLEAN') IS NULL
CREATE TABLE [clean].[PDF_TEXT_CLEAN] (
    [clean_id] int IDENTITY(1,1) NOT NULL,
    [pdf_id] int NOT NULL,
    [clean_text] nvarchar(MAX) NULL,
    [cleaned_on] datetime NULL,
    [company_id] int NOT NULL,
    [page_number] int NOT NULL,
    CONSTRAINT [PK_PDF_TEXT_CLEAN] PRIMARY KEY ([clean_id])
);
GO

-- foreign keys, applied after every table exists

IF OBJECT_ID('business.FK__COMPANY_M__compa__6EF57B66', 'F') IS NULL
ALTER TABLE [business].[COMPANY_METRICS] ADD CONSTRAINT [FK__COMPANY_M__compa__6EF57B66] FOREIGN KEY ([company_id]) REFERENCES [business].[COMPANY_MASTER] ([company_id]);
GO

IF OBJECT_ID('business.FK__HEALTH_FE__produ__693CA210', 'F') IS NULL
ALTER TABLE [business].[HEALTH_FEATURES] ADD CONSTRAINT [FK__HEALTH_FE__produ__693CA210] FOREIGN KEY ([product_id]) REFERENCES [business].[PRODUCT_MASTER] ([product_id]);
GO

IF OBJECT_ID('clean.FK__PDF_TEXT___pdf_i__60A75C0F', 'F') IS NULL
ALTER TABLE [clean].[PDF_TEXT_CLEAN] ADD CONSTRAINT [FK__PDF_TEXT___pdf_i__60A75C0F] FOREIGN KEY ([pdf_id]) REFERENCES [raw].[PDF_TEXT_RAW] ([pdf_id]);
GO

IF OBJECT_ID('business.FK__PREMIUM__product__6C190EBB', 'F') IS NULL
ALTER TABLE [business].[PREMIUM] ADD CONSTRAINT [FK__PREMIUM__product__6C190EBB] FOREIGN KEY ([product_id]) REFERENCES [business].[PRODUCT_MASTER] ([product_id]);
GO

IF OBJECT_ID('business.FK__PRODUCT_M__compa__66603565', 'F') IS NULL
ALTER TABLE [business].[PRODUCT_MASTER] ADD CONSTRAINT [FK__PRODUCT_M__compa__66603565] FOREIGN KEY ([company_id]) REFERENCES [business].[COMPANY_MASTER] ([company_id]);
GO

IF OBJECT_ID('clean.FK_CLEAN_COMPANY', 'F') IS NULL
ALTER TABLE [clean].[PDF_TEXT_CLEAN] ADD CONSTRAINT [FK_CLEAN_COMPANY] FOREIGN KEY ([company_id]) REFERENCES [business].[COMPANY_MASTER] ([company_id]);
GO

IF OBJECT_ID('raw.FK_RAW_COMPANY', 'F') IS NULL
ALTER TABLE [raw].[PDF_TEXT_RAW] ADD CONSTRAINT [FK_RAW_COMPANY] FOREIGN KEY ([company_id]) REFERENCES [business].[COMPANY_MASTER] ([company_id]);
GO
