"""
Quick sanity check on clean.PDF_TEXT_CLEAN.

    python read_clean_data.py

Prints the character count and first 1000 characters of a single cleaned
page, just to eyeball that clean_text.py produced something sensible
before running the heavier extraction stages against the whole table.
Change PDF_ID below to inspect a different page.
"""

import pyodbc

PDF_ID = 1

conn = pyodbc.connect(
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=AKSHAT\\SQLEXPRESS;"
    "DATABASE=INSURANCEDB;"
    "Trusted_Connection=yes;"
)
cursor = conn.cursor()

cursor.execute("""
SELECT clean_text
FROM clean.PDF_TEXT_CLEAN
WHERE pdf_id = ?
""", PDF_ID)

row = cursor.fetchone()

if row:
    clean_text = row.clean_text
    print("Characters:", len(clean_text))
    print("\nFirst 1000 characters:\n")
    print(clean_text[:1000])
else:
    print(f"No data found for pdf_id={PDF_ID}.")

conn.close()
