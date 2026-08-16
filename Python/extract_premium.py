"""
Rate chart -> business.PREMIUM

Age bands expand to individual ages: "36-45" writes ten rows.
"3m-35" starts at 0. ">75" runs to MAX_AGE.

Filters: 1A and 2A+2C only, SI >= 5,00,000, age <= 90,
         1-year policy term, never the "with buy back" chart.

Reading strategy:
    ruled tables    ABHI, Bajaj, HDFC ERGO, Niva Bupa, Tata AIG
    native words    Star Health   (PyMuPDF emits one line per CELL, so rows
                                   are rebuilt from word coordinates, then
                                   buffered per block because the plan-type
                                   cell is merged into the MIDDLE row)
    OCR             ICICI Lombard (image-only PDF)

Two guards keep worked examples out. HDFC ERGO's page 5 has an illustration
of the floater discount — "Plan: 2A + 2C ... Self 42 14,350 / Spouse 39
13,750 / Child 1 10 8,350" — which reads exactly like a rate table but is
four family members, not an age series. Tables headed with Member /
Discount / Illustrative are skipped, and any composition covering fewer
than MIN_AGES_PER_COMPOSITION distinct ages is discarded.
"""

import os
import re

import pdfplumber
import pyodbc

try:
    import pymupdf as fitz
    import pytesseract
    from PIL import Image
    OCR_AVAILABLE = True
except ImportError:
    try:
        import fitz
        import pytesseract
        from PIL import Image
        OCR_AVAILABLE = True
    except ImportError:
        OCR_AVAILABLE = False

# =====================================
# CONFIG
# =====================================

PDF_FOLDER = r"C:\Users\aksha\OneDrive\Desktop\insurance\PDFs"
TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

DRY_RUN = False
CLEAR_EXISTING = True

ALLOWED_COMPOSITIONS = {(1, 0), (2, 2)}
MIN_SUM_INSURED = 500000
SLAB_ROUNDING = 50000
MAX_AGE = 90
EXPAND_BANDS = True
MIN_AGES_PER_COMPOSITION = 10     # below this it is an illustration, not a chart

OCR_DPI = 300
OCR_PSM = 4
ROW_TOLERANCE = 4.0

# tables that are worked examples rather than rate grids
ILLUSTRATION_HEAD = re.compile(
    r"\bmember\b|\bdiscount\b|illustrat|model point|\bspouse\b", re.I)

FOLDER_TO_COMPANY_NAME = {
    "HDFC_ERGO": "HDFC ERGO",
    "ABHI": "ABHI",
    "BajajAllianz": "Bajaj Allianz",
    "CareHealth": "Care Health",
    "ICICI_Lombard": "ICICI Lombard",
    "NivaBupa": "Niva Bupa",
    "StarHealth": "Star Health",
    "TataAIG": "Tata AIG",
}

OCR_FILES = {"ICICI_Lombard_RateChart.pdf"}
LINE_TEXT_FILES = {"StarHealth_RateChart.pdf"}

PLAN_VARIANT = {"niva bupa": "bronze"}
VARIANT_WORDS = ["titanium", "platinum", "diamond", "gold", "silver", "bronze"]

if OCR_AVAILABLE:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

conn = pyodbc.connect(
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=AKSHAT\\SQLEXPRESS;"
    "DATABASE=INSURANCEDB;"
    "Trusted_Connection=yes;"
)
cursor = conn.cursor()
cursor.fast_executemany = True
print("Connected Successfully")

cursor.execute("""
SELECT p.product_id, c.company_name, p.product_name
FROM business.PRODUCT_MASTER p
JOIN business.COMPANY_MASTER c ON p.company_id = c.company_id
""")

product_map = {}
for row in cursor.fetchall():
    product_map[row.company_name.strip().lower()] = {
        "product_id": row.product_id,
        "product_name": row.product_name,
    }

for k, v in product_map.items():
    print(f"  {k:<16} -> {v['product_name']}")

# =====================================
# NUMBERS
# =====================================

def clean_number(value):
    if value is None:
        return None
    v = str(value)
    for junk in [",", "₹", "Rs.", "Rs", "/-", "*", " ", "|"]:
        v = v.replace(junk, "")
    v = v.strip()
    if not re.fullmatch(r"\d+", v or ""):
        return None
    return int(v)


def parse_sum_insured(value):
    """
    5,00,000 / 5L / 5 Lakhs / 1Cr -> rupees.
    Bare numbers must be round, or a premium like 52,235 is mistaken for a
    slab and the whole table parses against a garbage header.
    """
    if value is None:
        return None

    v = str(value).strip().lower()
    if v == "":
        return None

    v = v.replace(",", "").replace("₹", "").replace("rs.", "").replace("rs", "")
    v = v.replace("inr", "").strip()

    m = re.fullmatch(r"([\d.]+)\s*(lakhs?|lacs?|crores?|cr|l|c)", v)
    if m:
        try:
            n = float(m.group(1))
        except ValueError:
            return None
        val = int(n * 10000000) if m.group(2) in ("crores", "crore", "cr", "c") \
              else int(n * 100000)
        return val if val >= MIN_SUM_INSURED else None

    if re.fullmatch(r"\d+", v):
        n = int(v)
        if n < MIN_SUM_INSURED or n % SLAB_ROUNDING != 0:
            return None
        return n

    return None

# =====================================
# AGE BANDS
# =====================================

def parse_age_band(token):
    """3m-35 -> (0,35) | 36-45 -> (36,45) | >75 -> (76,90) | 35 -> (35,35)"""
    if token is None:
        return None

    t = str(token).strip()
    if t == "":
        return None

    for w in ["years", "year", "yrs", "yr", "age"]:
        t = re.sub(w, "", t, flags=re.IGNORECASE)
    t = t.strip()

    m = re.match(r"^[>≥]\s*(\d{1,3})$", t) or re.match(r"^(\d{1,3})\s*\+$", t)
    if m:
        lo = int(m.group(1)) + 1
        return (lo, MAX_AGE) if lo <= MAX_AGE else None

    m = re.match(r"^\d+\s*m\s*[-–_]\s*(\d{1,3})$", t, re.I)
    if m:
        return (0, min(int(m.group(1)), MAX_AGE))

    m = re.match(r"^(\d{1,3})\s*[-–_]\s*(\d{1,3})$", t)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        if lo > hi or lo > MAX_AGE:
            return None
        return (lo, min(hi, MAX_AGE))

    if re.fullmatch(r"\d{1,3}", t):
        a = int(t)
        return (a, a) if a <= MAX_AGE else None

    return None


def expand(band):
    lo, hi = band
    return list(range(lo, hi + 1)) if EXPAND_BANDS else [lo]

# =====================================
# COMPOSITION
# =====================================

PLAN_TYPE_LINE = re.compile(r'^\s*(\d)\s*A\s*(?:\+\s*(\d)\s*C)?\s*$', re.I)
PLAN_TYPE_PREFIX = re.compile(r'^\s*(\d)\s*A\s*(?:\+\s*(\d)\s*C)?\s+(\S.*)$', re.I)


def _comp(adults, children):
    if adults > 4 or children > 6:
        return None
    ftype = "Individual" if (adults == 1 and children == 0) else "Family Floater"
    return (ftype, adults, children)


def parse_plan_type_line(line):
    m = PLAN_TYPE_LINE.match(str(line or ""))
    if not m:
        return None
    return _comp(int(m.group(1)), int(m.group(2)) if m.group(2) else 0)


def split_plan_type_prefix(line):
    """'1A 56-60 18,700 ...' -> (composition, '56-60 18,700 ...')"""
    m = PLAN_TYPE_PREFIX.match(str(line))
    if not m:
        return None, line
    c = _comp(int(m.group(1)), int(m.group(2)) if m.group(2) else 0)
    return (c, m.group(3)) if c else (None, line)


WORD_TO_NUM = {"one": 1, "two": 2, "three": 3, "four": 4,
               "1": 1, "2": 2, "3": 3, "4": 4}


def parse_composition(text):
    if not text:
        return None
    t = str(text).strip().lower()
    if t == "" or len(t) > 70:
        return None

    m = re.search(
        r"(?:^|[\s(,:])(\d)\s*a(?:dults?)?\b\s*(?:\+\s*(\d)\s*c(?:hild(?:ren)?)?\b)?", t)
    if m:
        return _comp(int(m.group(1)), int(m.group(2)) if m.group(2) else 0)

    adults, children = None, 0

    m = re.search(r"(\w+)\s*adults?", t)
    if m and m.group(1) in WORD_TO_NUM:
        adults = WORD_TO_NUM[m.group(1)]

    m = re.search(r"(\w+)\s*(?:child|children|kids?)", t)
    if m and m.group(1) in WORD_TO_NUM:
        children = WORD_TO_NUM[m.group(1)]

    if adults is None and "self" in t:
        adults = 2 if "spouse" in t else 1
        if children == 0 and "child" in t:
            children = 1

    if adults is None:
        if "individual" in t:
            return ("Individual", 1, 0)
        if "floater" in t:
            return ("Family Floater", 2, 0)
        return None

    return _comp(adults, children)


def default_composition(product_name):
    p = product_name.lower()
    return ("Family Floater", 2, 2) if ("family" in p or "floater" in p) \
           else ("Individual", 1, 0)

# =====================================
# TIER AND VARIANT
# =====================================

def parse_tier(text):
    if not text:
        return None
    t = str(text)
    m = re.search(r"tier\s*[-]?\s*([123])", t, re.IGNORECASE)
    if m:
        return f"Tier {m.group(1)}"
    m = re.search(r"\bzone\s*([abc])\b", t, re.IGNORECASE)
    if m:
        return {"a": "Tier 1", "b": "Tier 2", "c": "Tier 3"}[m.group(1).lower()]
    if re.search(r"rest of india", t, re.IGNORECASE):
        return "Tier 2"
    return None


def parse_variant(text):
    if not text:
        return None
    t = str(text).lower()
    for word in VARIANT_WORDS:
        if re.search(rf"\b{word}\b", t):
            return word
    return None

# =====================================
# RULED TABLES
# =====================================

def table_is_empty(table):
    for row in table or []:
        for c in row or []:
            if c is not None and str(c).strip() != "":
                return False
    return True


def is_illustration(table):
    """Worked example rather than a rate grid."""
    head = " ".join(str(c) for r in table[:3] if r for c in r if c)
    return bool(ILLUSTRATION_HEAD.search(head))


def find_sum_insured_row(table):
    for i, row in enumerate(table):
        if row is None:
            continue
        slabs = []
        for j, cell in enumerate(row):
            n = parse_sum_insured(cell)
            if n is not None:
                slabs.append((j, n))
        if len(slabs) >= 2:
            return slabs, i
    return None, None


def find_age_column(table, start_row):
    if start_row >= len(table):
        return None
    ncols = max((len(r) for r in table[start_row:] if r), default=0)
    best_col, best_score = None, 0
    for col in range(min(ncols, 5)):
        good = total = 0
        for row in table[start_row:]:
            if row is None or col >= len(row):
                continue
            cell = row[col]
            if cell is None or str(cell).strip() == "":
                continue
            total += 1
            if parse_age_band(cell) is not None and parse_sum_insured(cell) is None:
                good += 1
        if total >= 3 and good > best_score:
            best_score, best_col = good, col
    return best_col


def premium_columns(table, start_row, age_col, n_slabs):
    """
    Columns holding premiums, right of the age column. Re-derived per table,
    because a continuation page can have a different column count from the
    page that carried the header.
    """
    ncols = max((len(r) for r in table[start_row:] if r), default=0)
    cols = []
    for col in range(ncols):
        if age_col is not None and col <= age_col:
            continue
        hits = 0
        for row in table[start_row:]:
            if row is None or col >= len(row):
                continue
            n = clean_number(row[col])
            if n is not None and n >= 500:
                hits += 1
        if hits >= 3:
            cols.append(col)
    return cols[:n_slabs]


def rows_from_tables(path, product_name, want_variant):
    pdf = pdfplumber.open(path)

    tier = "Tier 1"
    comp = default_composition(product_name)
    variant = None
    slab_values = None

    try:
        for page in pdf.pages:

            page_text = page.extract_text() or ""

            t = parse_tier(page_text)
            if t:
                tier = t

            for line in page_text.split("\n")[:6]:
                c = parse_composition(line)
                if c:
                    comp = c
                    break

            v = parse_variant(page_text)
            if v:
                variant = v

            for table in (page.extract_tables() or []):

                if table is None or len(table) < 3 or table_is_empty(table):
                    continue

                if is_illustration(table):
                    continue

                if want_variant:
                    tv = None
                    for r in table[:3]:
                        if r is None:
                            continue
                        tv = parse_variant(" ".join(str(c) for c in r if c))
                        if tv:
                            break
                    effective = tv or variant
                    if effective and effective != want_variant:
                        continue

                slabs, header_row = find_sum_insured_row(table)

                if slabs is not None:
                    slab_values = [v for _, v in slabs]
                    start = header_row + 1
                elif slab_values is not None:
                    start = 0
                else:
                    continue

                age_col = find_age_column(table, start)
                if age_col is None:
                    continue

                prem_cols = premium_columns(table, start, age_col, len(slab_values))
                if len(prem_cols) < 2:
                    continue

                pairs_map = list(zip(prem_cols, slab_values))

                for row in table[start:]:

                    if row is None or len(row) < 2:
                        continue

                    label = row[age_col] if age_col < len(row) else None

                    pt = parse_plan_type_line(label)
                    if pt is not None:
                        comp = pt
                        continue

                    band = parse_age_band(label)
                    if band is None:
                        rc = parse_composition(label)
                        if rc is not None:
                            comp = rc
                        continue

                    for col_index, insured in pairs_map:
                        if col_index >= len(row):
                            continue
                        premium = clean_number(row[col_index])
                        if premium is None or premium < 500 or premium >= insured:
                            continue
                        for age in expand(band):
                            yield tier, comp, insured, age, premium
    finally:
        pdf.close()

# =====================================
# LINE-BASED (native words and OCR)
# =====================================

def header_columns(line):
    """
    '5L 7.5L ... 300L Unlimited'      -> [(0,500000), ..., (9,None)]
    'Plan type Age band 5,00,000 ...' -> [(0,500000), (1,750000), ...]
    """
    tokens = re.findall(r"[\d.]+\s*L\b|unlimited", line, re.IGNORECASE)
    if len(tokens) >= 4:
        cols = []
        for i, tok in enumerate(tokens):
            if tok.lower().startswith("unlimited"):
                cols.append((i, None))
            else:
                cols.append((i, parse_sum_insured(tok.replace(" ", ""))))
        return cols

    vals = [parse_sum_insured(p) for p in line.split()]
    vals = [v for v in vals if v is not None]
    if len(vals) >= 4:
        return list(enumerate(vals))

    return None


def rows_from_lines(lines_by_page, want_variant, product_name):
    """
    Rows are buffered per block rather than emitted immediately, because
    Star Health merges the plan-type cell into the MIDDLE row of its block
    ('1A 56-60 18,700 ...'). Buffering lets the whole block be labelled
    once the plan type appears, wherever it sits.
    """
    tier = "Tier 1"
    carried = default_composition(product_name)
    variant = None
    columns = None
    in_scope = True

    block = []
    block_comp = None

    def flush(blk, comp_for_block):
        comp = comp_for_block or carried
        for band, pairs in blk:
            for insured, premium in pairs:
                for age in expand(band):
                    yield tier, comp, insured, age, premium

    for _, lines in lines_by_page:

        for line in lines:

            up = line.upper()

            # only real chart titles switch scope; "Buy Back Pre-Existing
            # Disease (Section 12)" is policy prose, not a chart heading
            if "PREMIUM CHART" in up:
                yield from flush(block, block_comp)
                block, block_comp = [], None
                if "BUY BACK" in up:
                    in_scope = False
                elif "FOR 1 YEAR" in up:
                    in_scope = True
                elif "FOR 2 YEAR" in up or "FOR 3 YEAR" in up:
                    in_scope = False
                continue

            if not in_scope:
                continue

            if ILLUSTRATION_HEAD.search(line):
                continue

            t = parse_tier(line)
            if t:
                tier = t

            v = parse_variant(line)
            if v:
                variant = v

            pt = parse_plan_type_line(line)
            if pt is not None:
                block_comp = pt
                carried = pt
                continue

            if re.search(r"adult|child|individual|floater|self", line, re.I):
                c = parse_composition(line)
                if c is not None:
                    block_comp = c
                    carried = c
                    continue

            hdr = header_columns(line)
            if hdr is not None:
                yield from flush(block, block_comp)
                block, block_comp = [], None
                columns = hdr
                continue

            if columns is None:
                continue

            if want_variant and variant and variant != want_variant:
                continue

            prefix_comp, line = split_plan_type_prefix(line)
            if prefix_comp is not None:
                block_comp = prefix_comp
                carried = prefix_comp

            parts = line.split()
            if not parts:
                continue

            band = parse_age_band(parts[0])
            if band is None:
                continue

            nums = [clean_number(p) for p in parts[1:]]
            nums = [n for n in nums if n is not None]

            if len(nums) != len(columns):
                continue

            pairs = [(insured, nums[idx])
                     for idx, insured in columns if insured is not None]

            # premiums must rise with cover across the row; a truncated
            # read breaks this and makes the whole row suspect
            vals = [p for _, p in pairs]
            if any(vals[i] > vals[i + 1] for i in range(len(vals) - 1)):
                continue

            pairs = [(si, pr) for si, pr in pairs if 500 <= pr < si]
            if pairs:
                block.append((band, pairs))

    yield from flush(block, block_comp)


def ocr_pages(path):
    doc = fitz.open(path)
    try:
        zoom = OCR_DPI / 72.0
        for pno in range(doc.page_count):
            pix = doc[pno].get_pixmap(matrix=fitz.Matrix(zoom, zoom))
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            text = pytesseract.image_to_string(img, config=f"--psm {OCR_PSM}")
            yield pno + 1, [l.strip() for l in text.split("\n") if l.strip()]
    finally:
        doc.close()


def native_pages(path):
    """
    PyMuPDF emits one text line per table CELL, so get_text() gives no
    usable rows. Visual rows are rebuilt by clustering words on their y
    coordinate and ordering them left to right.
    """
    doc = fitz.open(path)
    try:
        for pno in range(doc.page_count):
            words = doc[pno].get_text("words")
            if not words:
                yield pno + 1, []
                continue

            rows = {}
            for w in words:
                x0, y0, text = w[0], w[1], w[4]
                if not str(text).strip():
                    continue
                rows.setdefault(round(y0 / ROW_TOLERANCE), []).append((x0, str(text)))

            yield pno + 1, [" ".join(t for _, t in sorted(rows[k]))
                            for k in sorted(rows)]
    finally:
        doc.close()

# =====================================
# MAIN
# =====================================

if CLEAR_EXISTING and not DRY_RUN:
    cursor.execute("DELETE FROM business.PREMIUM")
    conn.commit()
    print("\nCleared business.PREMIUM")

print(f"\nFilters: {sorted(ALLOWED_COMPOSITIONS)}, SI >= {MIN_SUM_INSURED}, "
      f"age <= {MAX_AGE}, bands expanded, "
      f">= {MIN_AGES_PER_COMPOSITION} ages per composition")

INSERT_SQL = """
INSERT INTO business.PREMIUM
(product_id, age, family_type, sum_insured, premium_amount,
 adults, children, city_tier, policy_term)
VALUES (?,?,?,?,?,?,?,?,?)
"""

for file in sorted(os.listdir(PDF_FOLDER)):

    if not file.endswith("RateChart.pdf"):
        continue

    prefix = file.replace("_RateChart.pdf", "")
    company = FOLDER_TO_COMPANY_NAME.get(prefix, prefix.replace("_", " ")).lower()

    if company not in product_map:
        print(f"\n{file}: '{company}' not in PRODUCT_MASTER — skipped")
        continue

    product_id = product_map[company]["product_id"]
    product_name = product_map[company]["product_name"]
    want_variant = PLAN_VARIANT.get(company)

    path = os.path.join(PDF_FOLDER, file)

    print(f"\n{'='*70}")
    print(f"{file}  ->  {product_name}")
    if want_variant:
        print(f"  variant filter: {want_variant}")
    print(f"{'='*70}")

    if file in OCR_FILES and not OCR_AVAILABLE:
        print("  needs OCR but pytesseract/pymupdf not installed — skipped")
        continue

    try:
        if file in OCR_FILES:
            print("  reading by OCR (image-only PDF), this is slow...")
            source = rows_from_lines(ocr_pages(path), want_variant, product_name)
        elif file in LINE_TEXT_FILES:
            print("  rebuilding rows from word coordinates")
            source = rows_from_lines(native_pages(path), want_variant, product_name)
        else:
            source = rows_from_tables(path, product_name, want_variant)

        seen = {}
        dropped_comp = 0
        tiers, comps, slabs_seen, ages = set(), set(), set(), set()

        for tier, comp, insured, age, premium in source:

            family_type, adults, children = comp

            if (adults, children) not in ALLOWED_COMPOSITIONS:
                dropped_comp += 1
                continue

            key = (age, insured, family_type, adults, children, tier)
            if key in seen:
                continue
            seen[key] = premium

            tiers.add(tier)
            comps.add(comp)
            slabs_seen.add(insured)
            ages.add(age)

        # a genuine rate table spans many ages; a handful of rows for one
        # composition is a worked example that slipped through
        by_comp = {}
        for (age, si, ft, ad, ch, tr) in seen:
            by_comp.setdefault((ad, ch), set()).add(age)

        thin = {k for k, a in by_comp.items() if len(a) < MIN_AGES_PER_COMPOSITION}

        payload = [(product_id, age, ft, si, prem, ad, ch, tr, 1)
                   for (age, si, ft, ad, ch, tr), prem in seen.items()
                   if (ad, ch) not in thin]

        if not DRY_RUN and payload:
            cursor.executemany(INSERT_SQL, payload)
            conn.commit()

        print(f"  unique rows : {len(payload)}")
        print(f"  dropped     : {dropped_comp} wrong composition")
        if thin:
            print(f"  discarded   : {sorted(thin)} — too few ages, illustration")
        print(f"  ages        : {min(ages) if ages else '-'}-{max(ages) if ages else '-'}")
        print(f"  tiers       : {sorted(tiers)}")
        print(f"  slabs       : {sorted(slabs_seen)}")
        print(f"  compositions: {sorted(c for c in comps if (c[1], c[2]) not in thin)}")
        if DRY_RUN:
            print("  DRY_RUN — nothing written")
        if not payload:
            print("  >>> NOTHING KEPT — check this chart")

    except Exception as e:
        print(f"  FAILED: {e}")

# =====================================
# SUMMARY
# =====================================

print(f"\n{'='*70}\nPREMIUM EXTRACTION COMPLETED\n{'='*70}")

if not DRY_RUN:
    cursor.execute("""
        SELECT c.company_name, p.product_name, pr.city_tier,
               pr.adults, pr.children, COUNT(*), MIN(pr.age), MAX(pr.age)
        FROM business.PREMIUM pr
        JOIN business.PRODUCT_MASTER p ON p.product_id = pr.product_id
        JOIN business.COMPANY_MASTER c ON c.company_id = p.company_id
        GROUP BY c.company_name, p.product_name, pr.city_tier,
                 pr.adults, pr.children
        ORDER BY c.company_name, pr.city_tier, pr.adults, pr.children
    """)
    print("\nRows stored:")
    for name, prod, tier, ad, ch, n, lo, hi in cursor.fetchall():
        print(f"  {name:<15} {prod:<22} {tier:<8} {ad}A+{ch}C  "
              f"{n:>6}  ages {lo}-{hi}")

cursor.close()
conn.close()
print("\nDone.")