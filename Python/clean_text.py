"""
Stage 2 — raw.PDF_TEXT_RAW -> clean.PDF_TEXT_CLEAN

    python clean_text.py

Normalises the raw text pulled from PDFs (extract_pdf.py) so downstream
stages — premium extraction, health-feature extraction, the vector index —
all work from the same tidy source instead of each re-cleaning it their
own way.

Cleaning is deliberately shallow: tabs/carriage returns to spaces, runs of
spaces/blank lines collapsed, and outer whitespace trimmed. Nothing here
touches punctuation or casing, since the regex- and keyword-based parsers
downstream (extract_premium.py, extract_health_features.py) match against
the original wording.

Re-run whenever raw.PDF_TEXT_RAW changes — the table is cleared and
rebuilt from scratch each time, so this is safe to run repeatedly.
"""

import re

import pyodbc

# =====================================
# CONNECT
# =====================================

print("Script started")

conn = pyodbc.connect(
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=AKSHAT\\SQLEXPRESS;"
    "DATABASE=INSURANCEDB;"
    "Trusted_Connection=yes;"
)
cursor = conn.cursor()

# =====================================
# CLEAR OLD DATA
# =====================================

# full rebuild each run, so re-running after new pages land in
# raw.PDF_TEXT_RAW never leaves stale rows behind
cursor.execute("DELETE FROM clean.PDF_TEXT_CLEAN")
conn.commit()
print("Cleared clean.PDF_TEXT_CLEAN")

# =====================================
# READ RAW DATA
# =====================================

cursor.execute("""
SELECT
    pdf_id,
    company_id,
    page_number,
    raw_text
FROM raw.PDF_TEXT_RAW
ORDER BY pdf_id
""")

rows = cursor.fetchall()
print(f"Found {len(rows)} pages")

# =====================================
# CLEAN AND RE-INSERT
# =====================================

inserted = 0
skipped = 0

for row in rows:

    pdf_id = row.pdf_id
    company_id = row.company_id
    page_number = row.page_number
    raw_text = row.raw_text

    if raw_text is None:
        skipped += 1
        continue

    clean_text = raw_text
    clean_text = clean_text.replace("\t", " ")          # tabs -> single space
    clean_text = clean_text.replace("\r", " ")           # stray carriage returns
    clean_text = re.sub(r" +", " ", clean_text)          # collapse runs of spaces
    clean_text = re.sub(r"\n+", "\n", clean_text)        # collapse blank lines
    clean_text = clean_text.strip()

    if clean_text == "":
        skipped += 1
        continue

    cursor.execute("""
    INSERT INTO clean.PDF_TEXT_CLEAN
    (
        pdf_id,
        company_id,
        page_number,
        clean_text,
        cleaned_on
    )
    VALUES (?, ?, ?, ?, GETDATE())
    """,
    pdf_id,
    company_id,
    page_number,
    clean_text
    )

    inserted += 1

    # commit in batches rather than once at the end, so a crash partway
    # through a large run doesn't lose everything already cleaned
    if inserted % 500 == 0:
        conn.commit()
        print(f"  {inserted} inserted...")

conn.commit()

print(f"{inserted} pages inserted into clean.PDF_TEXT_CLEAN")
print(f"{skipped} empty pages skipped")

# =====================================
# SUMMARY
# =====================================

cursor.execute("""
SELECT m.company_name, COUNT(*)
FROM clean.PDF_TEXT_CLEAN c
JOIN business.company_master m ON m.company_id = c.company_id
GROUP BY m.company_name
ORDER BY m.company_name
""")

print("\nPages per company:")
for name, count in cursor.fetchall():
    print(f"  {name:<25} {count}")

cursor.close()
conn.close()

print("\nCleaning completed successfully.")
