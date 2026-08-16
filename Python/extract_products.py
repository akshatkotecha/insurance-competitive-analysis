"""
Seed business.PRODUCT_MASTER with the one flagship health policy tracked
per insurer.

    python extract_products.py

The product names below were chosen by hand — each insurer sells dozens
of health policies, but this project follows only the flagship retail
plan per company so that premiums, features and financials all line up
against the same product. Idempotent: existing (company, product) pairs
are skipped, so re-running after adding a new insurer only inserts the
new rows.
"""

import pyodbc

# =====================================
# CONNECT
# =====================================

conn = pyodbc.connect(
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=AKSHAT\\SQLEXPRESS;"
    "DATABASE=INSURANCEDB;"
    "Trusted_Connection=yes;"
)
cursor = conn.cursor()
print("Connected Successfully")

# =====================================
# FLAGSHIP PRODUCT PER INSURER
# =====================================
# each insurer maps to the same product name across all three document
# types (Brochure, Prospectus, RateChart), since they all describe the
# same policy

PRODUCTS = {

    "HDFC ERGO": {
        "Brochure": ("Optima Secure", "Health Insurance", "Individual"),
        "Prospectus": ("Optima Secure", "Health Insurance", "Individual"),
        "RateChart": ("Optima Secure", "Health Insurance", "Individual"),
    },

    "ICICI Lombard": {
        "Brochure": ("Health AdvantEdge", "Health Insurance", "Individual"),
        "Prospectus": ("Health AdvantEdge", "Health Insurance", "Individual"),
        "RateChart": ("Health AdvantEdge", "Health Insurance", "Individual"),
    },

    "Care Health": {
        "Brochure": ("Care Supreme", "Health Insurance", "Individual"),
        "Prospectus": ("Care Supreme", "Health Insurance", "Individual"),
        "RateChart": ("Care Supreme", "Health Insurance", "Individual"),
    },

    "Star Health": {
        "Brochure": ("Young Star", "Health Insurance", "Individual"),
        "Prospectus": ("Young Star", "Health Insurance", "Individual"),
        "RateChart": ("Young Star", "Health Insurance", "Individual"),
    },

    "Niva Bupa": {
        "Brochure": ("ReAssure 2.0", "Health Insurance", "Individual"),
        "Prospectus": ("ReAssure 2.0", "Health Insurance", "Individual"),
        "RateChart": ("ReAssure 2.0", "Health Insurance", "Individual"),
    },

    "Bajaj Allianz": {
        "Brochure": ("Health Guard", "Health Insurance", "Individual"),
        "Prospectus": ("Health Guard", "Health Insurance", "Individual"),
        "RateChart": ("Health Guard", "Health Insurance", "Individual"),
    },

    "Tata AIG": {
        "Brochure": ("MediCare Premier", "Health Insurance", "Individual"),
        "Prospectus": ("MediCare Premier", "Health Insurance", "Individual"),
        "RateChart": ("MediCare Premier", "Health Insurance", "Individual"),
    },

    "ABHI": {
        "Brochure": ("Activ Health Platinum", "Health Insurance", "Individual"),
        "Prospectus": ("Activ Health Platinum", "Health Insurance", "Individual"),
        "RateChart": ("Activ Health Platinum", "Health Insurance", "Individual"),
    },

}

# =====================================
# LOOK UP COMPANY IDS
# =====================================

cursor.execute("""
SELECT company_id, company_name
FROM business.COMPANY_MASTER
""")

company_map = {row.company_name: row.company_id for row in cursor.fetchall()}
print(company_map)

# =====================================
# INSERT PRODUCTS
# =====================================
# the dict has one entry per document type, but all three point at the
# same product — only the product itself needs inserting, once

inserted = 0

for company, documents in PRODUCTS.items():

    if company not in company_map:
        print(f"{company} not found in COMPANY_MASTER")
        continue

    company_id = company_map[company]

    for product_name, insurance_type, category in documents.values():

        cursor.execute("""
        SELECT COUNT(*)
        FROM business.PRODUCT_MASTER
        WHERE company_id = ?
          AND product_name = ?
        """,
        company_id,
        product_name,
        )

        if cursor.fetchone()[0] > 0:
            continue  # already seeded

        cursor.execute("""
        INSERT INTO business.PRODUCT_MASTER
        (
            company_id,
            product_name,
            insurance_type,
            category
        )
        VALUES (?, ?, ?, ?)
        """,
        company_id,
        product_name,
        insurance_type,
        category,
        )

        inserted += 1

conn.commit()

print(f"{inserted} products inserted")

cursor.close()
conn.close()

print("Finished")
