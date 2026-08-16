"""
Stage 4 — business.HEALTH_FEATURES

Reliable    : waiting_period, ped_waiting, room_rent,
              pre_hospitalization, post_hospitalization, ambulance_cover
Provisional : the 0/1 flags mean "described positively in the document",
              not "covered in the base plan". Brochures describe riders
              and plan variants in the same prose.

Known data quirk: a NULL ambulance_cover can mean "up to sum insured"
(Niva Bupa) rather than "not covered". NULL is not the same as absent.
"""

import re

import pyodbc

DRY_RUN = False
CLEAR_EXISTING = True

WINDOW = 400

NEGATION = [
    "not covered", "not payable", "excluded", "exclusion", "shall not",
    "is not", "are not", "no cover", "not applicable", "not available",
    "does not cover", "will not be", "not indemnif",
]

# phrases that mark a glossary entry rather than a benefit value
DEFINITION_MARKERS = r"means|shall mean|is defined as|refers to|definition"

conn = pyodbc.connect(
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=AKSHAT\\SQLEXPRESS;"
    "DATABASE=INSURANCEDB;"
    "Trusted_Connection=yes;"
)
cursor = conn.cursor()
print("Connected Successfully")

# ==============================
# LOAD
# ==============================

cursor.execute("""
SELECT p.product_id, p.product_name, c.clean_text
FROM clean.PDF_TEXT_CLEAN c
INNER JOIN raw.PDF_TEXT_RAW r ON c.pdf_id = r.pdf_id
INNER JOIN business.COMPANY_MASTER cm ON r.company_name = cm.company_name
INNER JOIN business.PRODUCT_MASTER p ON cm.company_id = p.company_id
WHERE r.document_type IN ('Brochure','Prospectus')
ORDER BY p.product_id, r.page_number;
""")

rows = cursor.fetchall()
print("Pages Loaded :", len(rows))

products, names = {}, {}
for row in rows:
    products.setdefault(row.product_id, []).append(row.clean_text or "")
    names[row.product_id] = row.product_name

products = {pid: "\n".join(v) for pid, v in products.items()}
print("Products Found :", len(products))

# ==============================
# HELPERS
# ==============================

def windows_around(text, keywords, size=WINDOW):
    out, low = [], text.lower()
    for kw in keywords:
        start = 0
        while True:
            i = low.find(kw.lower(), start)
            if i == -1:
                break
            out.append(text[max(0, i - 120): i + size])
            start = i + 1
    return out


def is_negated(chunk):
    low = chunk.lower()
    return any(n in low for n in NEGATION)


def covered(text, keywords):
    chunks = windows_around(text, keywords, size=250)
    if not chunks:
        return 0
    pos = sum(1 for c in chunks if not is_negated(c))
    return 1 if pos > (len(chunks) - pos) else 0


def number_near(text, keywords, unit_pattern, size=WINDOW, lo=None, hi=None):
    """
    Most common number with the given unit, near a keyword.
    Glossary chunks are skipped — "pre-hospitalization means expenses
    incurred during a pre-defined number of days" contains no real value.
    """
    found = []
    for chunk in windows_around(text, keywords, size):
        if re.search(DEFINITION_MARKERS, chunk[:220], re.I):
            continue
        for m in re.finditer(unit_pattern, chunk, re.I):
            try:
                val = int(m.group(1))
            except (ValueError, IndexError):
                continue
            if lo is not None and val < lo:
                continue
            if hi is not None and val > hi:
                continue
            found.append(val)
    return max(set(found), key=found.count) if found else None


def money_near(text, keywords, size=WINDOW):
    found = []
    for chunk in windows_around(text, keywords, size):
        for pat in [r'₹\s*([\d,]+)', r'INR\s*([\d,]+)', r'Rs\.?\s*([\d,]+)']:
            for m in re.finditer(pat, chunk, re.I):
                try:
                    val = int(m.group(1).replace(",", ""))
                except ValueError:
                    continue
                if 500 <= val <= 200000:
                    found.append(val)
    return max(set(found), key=found.count) if found else None


def ped_waiting(text):
    """PED is normally stated in months (36/48). A 1-year answer is a misread."""
    kws = ["pre-existing", "pre existing", "ped waiting"]
    months = number_near(text, kws, r'(\d+)\s*months?', size=250, lo=12, hi=60)
    if months:
        return f"{months // 12} Years"
    years = number_near(text, kws, r'(\d+)\s*(?:years?|yrs?)', size=250, lo=2, hi=5)
    return f"{years} Years" if years else None


def room_rent_type(text):
    joined = " ".join(windows_around(
        text, ["room rent", "room category", "room, boarding", "accommodation"], 300))
    if not joined:
        return None
    for pattern, label in [
        (r"single\s+private\s+a/?c\s+room", "Single Private AC Room"),
        (r"single\s+private\s+room", "Single Private Room"),
        (r"at\s+actuals?", "At Actuals"),
        (r"no\s+room\s+rent\s+(?:capping|limit|sub-?limit)", "No Limit"),
        (r"any\s+room", "Any Room"),
        (r"private\s+room", "Private Room"),
        (r"shared\s+room", "Shared Room"),
        (r"(\d+)\s*%\s*of\s*(?:the\s*)?sum\s*insured", "% of Sum Insured"),
    ]:
        if re.search(pattern, joined, re.I):
            return label
    return "Mentioned"

# ==============================
# PROCESS
# ==============================

if CLEAR_EXISTING and not DRY_RUN:
    cursor.execute("DELETE FROM business.HEALTH_FEATURES")
    conn.commit()
    print("Cleared business.HEALTH_FEATURES")

for product_id, text in sorted(products.items()):

    print(f"\n{'='*60}\nProduct {product_id}: {names.get(product_id,'?')}\n{'='*60}")

    initial = number_near(
        text,
        ["initial waiting period", "waiting period of", "first 30 days",
         "30 days waiting", "days waiting period"],
        r'(\d+)\s*days?', lo=15, hi=120)
    waiting = f"{initial} Days" if initial else None

    ped = ped_waiting(text)
    room = room_rent_type(text)

    pre = number_near(text,
                      ["pre-hospitalization", "pre hospitalization",
                       "pre-hospitalisation", "pre hospitalisation"],
                      r'(\d+)\s*days?', size=200, lo=15, hi=120)

    post = number_near(text,
                       ["post-hospitalization", "post hospitalization",
                        "post-hospitalisation", "post hospitalisation"],
                       r'(\d+)\s*days?', size=200, lo=30, hi=200)

    ambulance = money_near(text, ["ambulance"], size=300)

    opd = covered(text, ["opd", "out patient", "outpatient"])
    maternity = covered(text, ["maternity", "delivery charges", "child birth"])
    restoration = covered(text, ["restore", "restoration", "reinstatement",
                                 "refill of sum insured"])
    ncb = covered(text, ["no claim bonus", "no-claim bonus", "cumulative bonus"])
    ayush = covered(text, ["ayush", "ayurveda", "homeopathy", "unani"])
    daycare = covered(text, ["day care", "day-care", "daycare procedure"])
    organ = covered(text, ["organ donor", "organ transplant"])
    domiciliary = covered(text, ["domiciliary"])
    checkup = covered(text, ["health check-up", "health checkup",
                             "preventive health check"])
    consumables = covered(text, ["consumables", "non-medical items",
                                 "non medical expenses"])

    print(f"  waiting {waiting} | ped {ped} | room {room}")
    print(f"  pre {pre} | post {post} | ambulance {ambulance}")
    print(f"  opd {opd} maternity {maternity} restore {restoration} "
          f"ncb {ncb} ayush {ayush}")
    print(f"  daycare {daycare} organ {organ} domiciliary {domiciliary} "
          f"checkup {checkup} consumables {consumables}")

    if DRY_RUN:
        continue

    cursor.execute(
        "SELECT COUNT(*) FROM business.HEALTH_FEATURES WHERE product_id=?",
        product_id)
    if cursor.fetchone()[0] > 0:
        print("  already exists — skipped")
        continue

    cursor.execute("""
    INSERT INTO business.HEALTH_FEATURES
    (product_id, waiting_period, ped_waiting, room_rent,
     opd_cover, maternity_cover, restoration, ncb, ayush_cover,
     pre_hospitalization, post_hospitalization, day_care,
     organ_donor, domiciliary_treatment, annual_health_checkup,
     ambulance_cover, consumables_cover)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """,
    product_id, waiting, ped, room,
    opd, maternity, restoration, ncb, ayush,
    pre, post, daycare, organ, domiciliary, checkup,
    ambulance, consumables)

    print("  inserted")

if not DRY_RUN:
    conn.commit()

    cursor.execute("""
        SELECT c.company_name, p.product_name, h.waiting_period, h.ped_waiting,
               h.room_rent, h.pre_hospitalization, h.post_hospitalization,
               h.ambulance_cover
        FROM business.HEALTH_FEATURES h
        JOIN business.PRODUCT_MASTER p ON p.product_id = h.product_id
        JOIN business.COMPANY_MASTER c ON c.company_id = p.company_id
        ORDER BY c.company_name
    """)
    print(f"\n{'='*60}\nStored\n{'='*60}")
    for r in cursor.fetchall():
        print(f"  {r[0]:<15} {r[1]:<22} wait {str(r[2]):<9} ped {str(r[3]):<9} "
              f"room {str(r[4]):<24} pre {r[5]} post {r[6]} amb {r[7]}")

    cursor.execute("""
        SELECT c.company_name, p.product_name
        FROM business.HEALTH_FEATURES h
        JOIN business.PRODUCT_MASTER p ON p.product_id = h.product_id
        JOIN business.COMPANY_MASTER c ON c.company_id = p.company_id
        WHERE h.waiting_period IS NULL OR h.pre_hospitalization IS NULL
           OR h.post_hospitalization IS NULL OR h.ped_waiting IS NULL
    """)
    gaps = cursor.fetchall()
    if gaps:
        print("\nProducts with gaps — fill these by hand from the brochure:")
        for g in gaps:
            print(f"  {g[0]} / {g[1]}")

cursor.close()
conn.close()
print("\nDone.")