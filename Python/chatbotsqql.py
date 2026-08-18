"""
Insurance chatbot — SQL only.

    streamlit run chatbotsqql.py

Every answer is a database lookup. Nothing is generated.

Routing order
-------------
1. Deterministic parsing. Ages, cover amounts, insurer names and metric
   names are pulled out with regex against the actual database contents.
   These are reliable, so they run first.
2. Keyword routing. If the question names a metric, a policy term, or a
   glossary entry, that decides the route — no model needed.
3. The LLM, only when steps 1 and 2 are inconclusive.

The earlier version called the model first and fell through to the
glossary whenever it returned "unclear". That made "ABHI GWP" answer with
the definition of GWP instead of ABHI's figures. Deterministic signals now
win, and the glossary is a last resort that never fires when a company is
named or a number is present.

Prerequisites:
    pip install streamlit plotly pyodbc pandas requests
    set GROQ_API_KEY=your-groq-api-key    (optional — the bot works without
                                            it, falling back to "unclear".
                                            Free, no card, from console.groq.com)
"""

import json
import os
import re
from datetime import datetime

import pandas as pd
import plotly.express as px
import pyodbc
import requests
import streamlit as st

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
LLM_AVAILABLE = bool(GROQ_API_KEY)

# =====================================
# CONFIG
# =====================================

LOG_PATH = r"C:\Users\aksha\OneDrive\Desktop\insurance\chatbot_log.csv"

CONN_STR = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=AKSHAT\\SQLEXPRESS;"
    "DATABASE=INSURANCEDB;"
    "Trusted_Connection=yes;"
)

NO_DATA = ("I'm sorry — I don't have that in my database. I can answer "
           "questions about premiums by age and cover, policy terms like "
           "waiting periods and room rent, and company financials such as "
           "GWP, ROE and solvency ratio.")

# =====================================
# DATA HELPERS
# =====================================

@st.cache_resource
def get_conn():
    return pyodbc.connect(CONN_STR)


@st.cache_data(ttl=600)
def load_companies():
    return pd.read_sql("""
        SELECT c.company_name, p.product_name
        FROM business.PRODUCT_MASTER p
        JOIN business.COMPANY_MASTER c ON c.company_id = p.company_id
        ORDER BY c.company_name
    """, get_conn())


@st.cache_data(ttl=600)
def load_slabs():
    return pd.read_sql(
        "SELECT DISTINCT sum_insured FROM business.PREMIUM ORDER BY sum_insured",
        get_conn())["sum_insured"].tolist()


@st.cache_data(ttl=600)
def load_age_range():
    df = pd.read_sql(
        "SELECT MIN(age) AS lo, MAX(age) AS hi FROM business.PREMIUM",
        get_conn())
    return int(df.iloc[0]["lo"]), int(df.iloc[0]["hi"])


@st.cache_data(ttl=600)
def load_metric_names():
    try:
        return pd.read_sql(
            "SELECT DISTINCT metric_name FROM business.vw_metrics_long",
            get_conn())["metric_name"].tolist()
    except Exception:
        return []


# nicknames people actually type, mapped to how the company is stored
COMPANY_ALIASES = {
    "abhi": "ABHI",
    "aditya birla": "ABHI",
    "birla": "ABHI",
    "hdfc": "HDFC ERGO",
    "ergo": "HDFC ERGO",
    "optima": "HDFC ERGO",
    "icici": "ICICI Lombard",
    "lombard": "ICICI Lombard",
    "elevate": "ICICI Lombard",
    "star": "Star Health",
    "niva": "Niva Bupa",
    "bupa": "Niva Bupa",
    "reassure": "Niva Bupa",
    "bajaj": "Bajaj Allianz",
    "allianz": "Bajaj Allianz",
    "tata": "Tata AIG",
    "aig": "Tata AIG",
    "care": "Care Health",
}

# question wording -> the column that answers it
TERM_COLUMNS = {
    "waiting period":  ("waiting_period", "initial waiting period"),
    "waiting":         ("waiting_period", "initial waiting period"),
    "ped":             ("ped_waiting", "pre-existing disease waiting"),
    "pre-existing":    ("ped_waiting", "pre-existing disease waiting"),
    "pre existing":    ("ped_waiting", "pre-existing disease waiting"),
    "room rent":       ("room_rent", "room rent limit"),
    "room":            ("room_rent", "room rent limit"),
    "pre-hospital":    ("pre_hospitalization", "pre-hospitalisation days"),
    "pre hospital":    ("pre_hospitalization", "pre-hospitalisation days"),
    "post-hospital":   ("post_hospitalization", "post-hospitalisation days"),
    "post hospital":   ("post_hospitalization", "post-hospitalisation days"),
    "ambulance":       ("ambulance_cover", "ambulance cover"),
    "opd":             ("opd_cover", "OPD cover"),
    "maternity":       ("maternity_cover", "maternity cover"),
    "restoration":     ("restoration", "restoration benefit"),
    "restore":         ("restoration", "restoration benefit"),
    "no claim bonus":  ("ncb", "no claim bonus"),
    "ncb":             ("ncb", "no claim bonus"),
    "ayush":           ("ayush_cover", "AYUSH cover"),
    "day care":        ("day_care", "day care procedures"),
    "daycare":         ("day_care", "day care procedures"),
    "organ":           ("organ_donor", "organ donor cover"),
    "domiciliary":     ("domiciliary_treatment", "domiciliary treatment"),
    "health check":    ("annual_health_checkup", "annual health checkup"),
    "checkup":         ("annual_health_checkup", "annual health checkup"),
    "consumable":      ("consumables_cover", "consumables cover"),
}

BOOLEAN_COLUMNS = {
    "opd_cover", "maternity_cover", "restoration", "ncb", "ayush_cover",
    "day_care", "organ_donor", "domiciliary_treatment",
    "annual_health_checkup", "consumables_cover",
}

# question wording -> metric_name as stored
METRIC_WORDS = {
    "gwp": "GWP",
    "gross written": "GWP",
    "gross premium": "GWP",
    "gdpi": "GDPI",
    "gross direct": "GDPI",
    "roe": "ROE",
    "return on equity": "ROE",
    "roa": "ROA",
    "return on assets": "ROA",
    "solvency": "Solvency Ratio",
    "combined ratio": "Combined Ratio",
    "market share": "Market Share",
    "net worth": "Net Worth",
    "networth": "Net Worth",
    "aum": "AUM",
    "assets under management": "AUM",
    "icr": "ICR",
    "incurred claims": "ICR",
    "csr": "CSR",
    "claim settlement": "CSR",
}

PREMIUM_WORDS = ["premium", "price", "cost", "quote", "rate", "charge",
                 "cheapest", "cheaper", "expensive", "compare", "vs",
                 "versus", "how much"]

# =====================================
# DETERMINISTIC PARSING — runs before the model
# =====================================

def find_companies(text):
    t = text.lower()
    found = []
    known = load_companies()["company_name"].unique().tolist()

    for name in known:
        if name.lower() in t and name not in found:
            found.append(name)

    for alias, name in COMPANY_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", t) and name not in found:
            if name in known:
                found.append(name)

    return found


def find_age(text):
    patterns = [
        r"\b(\d{1,2})\s*(?:year|yr|y)s?\s*old\b",
        r"\bage[d]?\s*(?:of\s*)?(\d{1,2})\b",
        r"\b(\d{1,2})\s*(?:year|yr)s?\b",
        r"\bfor\s+a\s+(\d{1,2})\b",
    ]
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            a = int(m.group(1))
            if 0 <= a <= 100:
                return a
    return None


def find_sum_insured(text):
    """10L / 10 lakh / 1cr / 1 crore / 1000000 -> rupees"""
    m = re.search(r"\b(\d+(?:\.\d+)?)\s*(cr|crore|crores)\b", text, re.I)
    if m:
        return int(float(m.group(1)) * 10000000)

    m = re.search(r"\b(\d+(?:\.\d+)?)\s*(l|lakh|lakhs|lac|lacs)\b", text, re.I)
    if m:
        return int(float(m.group(1)) * 100000)

    m = re.search(r"\b(\d{6,9})\b", text)
    if m:
        return int(m.group(1))

    return None


def find_metric(text):
    t = text.lower()
    known = load_metric_names()
    for phrase, metric in sorted(METRIC_WORDS.items(), key=lambda x: -len(x[0])):
        if re.search(rf"\b{re.escape(phrase)}\b", t):
            if not known or metric in known:
                return metric
    return None


def find_term(text):
    t = text.lower()
    for phrase, (col, label) in sorted(TERM_COLUMNS.items(),
                                       key=lambda x: -len(x[0])):
        if phrase in t:
            return col, label
    return None, None


def find_year(text):
    """Financial years are stored as FY21..FY25 (fy_number 2021..2025).
    Returns (year, year_range): year is a single fy_number, year_range is
    a (lo, hi) pair of fy_numbers. At most one of the two is set.
    "FY23", "2023" and "fy 2023" all resolve to fy_number 2023; "2021 to
    2023" or "FY21-FY23" resolve to a range.
    """
    t = text.lower()

    def norm(s):
        n = int(s)
        return n + 2000 if n < 100 else n

    m = re.search(
        r"\bfy\s*[- ]?(\d{2,4})\s*(?:to|-|–|through|and)\s*fy?\s*[- ]?(\d{2,4})\b", t)
    if m:
        return None, tuple(sorted((norm(m.group(1)), norm(m.group(2)))))

    m = re.search(r"\b(20\d{2})\s*(?:to|-|–|through)\s*(20\d{2})\b", t)
    if m:
        return None, tuple(sorted((int(m.group(1)), int(m.group(2)))))

    m = re.search(r"\bfy\s*[- ]?(\d{2,4})\b", t)
    if m:
        return norm(m.group(1)), None

    m = re.search(r"\b(20\d{2})\b", t)
    if m:
        return int(m.group(1)), None

    return None, None


def wants_average(text):
    return bool(re.search(r"\b(average|avg|mean)\b", text.lower()))


def wants_family(text):
    t = text.lower()
    return bool(re.search(r"family|floater|\b2a\s*\+?\s*2c\b|spouse|"
                          r"husband|wife|kids|children", t))


def nearest_slab(si):
    slabs = load_slabs()
    if not slabs or si is None:
        return None
    return min(slabs, key=lambda s: abs(s - si))

# =====================================
# ROUTING — deterministic first, model last
# =====================================

def route(question):
    """
    Returns a dict describing what to do. Every field that can be parsed
    reliably is parsed here; the model is consulted only when the route is
    still unclear.
    """
    companies = find_companies(question)
    age = find_age(question)
    si = find_sum_insured(question)
    metric = find_metric(question)
    term_col, term_label = find_term(question)
    family = wants_family(question)
    year, year_range = find_year(question)
    average = wants_average(question)
    t = question.lower()

    plan = {"companies": companies, "age": age, "sum_insured": si,
            "metric": metric, "term_col": term_col, "term_label": term_label,
            "family": family, "year": year, "year_range": year_range,
            "average": average, "source": "rules"}

    asks_definition = bool(re.search(
        r"\b(what is|what does|what's|meaning of|mean by|explain|define)\b", t))

    # a number or a price word means they want a premium
    price_signal = any(w in t for w in PREMIUM_WORDS)

    if price_signal or (age is not None and si is not None):
        plan["intent"] = "premium"
        return plan

    # a named metric wins over a definition: "ABHI GWP" wants the figure,
    # not the meaning of GWP. A year or "average" is just as decisive —
    # "average GWP in 2023" is not asking what GWP means either, even with
    # no company named
    if metric and (companies or average or year or year_range or not asks_definition):
        plan["intent"] = "metric"
        return plan

    if term_col and companies:
        plan["intent"] = "terms"
        return plan

    if term_col and not asks_definition:
        plan["intent"] = "terms"
        return plan

    if asks_definition:
        plan["intent"] = "glossary"
        return plan

    # a company named with nothing else: show what we hold for it
    if companies and not asks_definition:
        plan["intent"] = "profile"
        return plan

    # nothing decisive — ask the model
    if LLM_AVAILABLE:
        guess = ask_model(question)
        if guess:
            plan.update({k: v for k, v in guess.items() if v is not None})
            plan["source"] = "model"
            return plan

    plan["intent"] = "unclear"
    return plan


def ask_model(question):
    """Last-resort routing via Groq, only reached when deterministic parsing
    and keyword routing both come up empty. The prompt is grounded in the
    database's actual companies, metrics and terms, and asks for the same
    fields the deterministic parsers extract — company, metric, age, cover,
    year and whether an average is wanted — so a question that slips past
    the regexes (unusual phrasing, a typo'd insurer name) still comes back
    with a usable, structured route instead of just an intent label.
    """
    if not LLM_AVAILABLE:
        return None

    known_companies = load_companies()["company_name"].unique().tolist()
    known_metrics = load_metric_names() or sorted(set(METRIC_WORDS.values()))
    known_terms = sorted(set(label for _, label in TERM_COLUMNS.values()))

    prompt = f"""You are the routing layer for a health-insurance database \
chatbot. Every answer the bot gives is a direct SQL lookup — you never \
generate the final answer, you only decide which lookup fits the question \
and pull out the values it needs.

Insurers in the database: {", ".join(known_companies)}
Metrics in the database: {", ".join(known_metrics)}
Policy terms the bot can look up: {", ".join(known_terms)}
Financial years held: FY21 to FY25 (FY23 = calendar year 2023)

Pick exactly one intent:
- "premium"  — asking a price/quote for cover (usually names an age and/or
  a cover amount)
- "terms"    — asking about a policy feature: waiting period, room rent,
  PED, maternity, OPD, restoration, NCB, etc, or whether something is
  covered
- "metric"   — asking for a company financial figure such as GWP, ROE,
  solvency ratio, combined ratio, market share, AUM, ICR or CSR — including
  an average of one over a year or a range of years
- "glossary" — asking what a term MEANS in general, with no company, year,
  or the word average/avg attached (e.g. "what is GWP?"). If a company, a
  year, or "average" is present, it is NOT glossary — route it to "metric"
  or "terms" instead, since the person wants the actual figure
- "profile"  — asking generally about one insurer with nothing specific
- "unclear"  — none of the above fit

Also extract, only when present in the question:
- company: the insurer name as it appears in the list above, or the
  closest match
- metric: the metric name as it appears in the list above
- age: the age in years, for a premium question
- sum_insured_lakhs: the cover amount in lakhs (10000000 rupees = 100)
- year: a single financial year as a 4-digit number — "FY23" and "2023"
  both mean 2023
- year_end: set only for a RANGE of years, e.g. "2021 to 2023" means
  year=2021, year_end=2023
- average: true if the question uses the word "average", "avg" or "mean"

Examples:
"average GWP for ABHI in 2023" -> {{"intent": "metric", "company": "ABHI", \
"metric": "GWP", "year": 2023, "average": true}}
"what was ICICI Lombard's solvency ratio between 2022 and 2024" -> \
{{"intent": "metric", "company": "ICICI Lombard", "metric": "Solvency \
Ratio", "year": 2022, "year_end": 2024}}
"does star health cover maternity" -> {{"intent": "terms", "company": \
"Star Health"}}
"what is a combined ratio" -> {{"intent": "glossary"}}
"combined ratio for all insurers in FY24" -> {{"intent": "metric", \
"metric": "Combined Ratio", "year": 2024}}

Question: {question}

Reply with ONLY a JSON object with keys chosen from: intent, company,
metric, age, sum_insured_lakhs, year, year_end, average. Omit any key you
have no value for.
"""

    try:
        resp = requests.post(
            GROQ_API_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}",
                     "Content-Type": "application/json"},
            json={
                "model": GROQ_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "response_format": {"type": "json_object"},
            },
            timeout=15,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        d = json.loads(content)
    except Exception:
        return None

    out = {"intent": d.get("intent")}

    if d.get("age"):
        try:
            out["age"] = int(d["age"])
        except (TypeError, ValueError):
            pass

    if d.get("sum_insured_lakhs"):
        try:
            out["sum_insured"] = int(float(d["sum_insured_lakhs"]) * 100000)
        except (TypeError, ValueError):
            pass

    if d.get("company"):
        matched = find_companies(str(d["company"]))
        if matched:
            out["companies"] = matched

    if d.get("metric"):
        m = str(d["metric"]).strip()
        if not known_metrics or m in known_metrics:
            out["metric"] = m
        else:
            low = m.lower()
            for phrase, name in METRIC_WORDS.items():
                if phrase in low or low in phrase:
                    out["metric"] = name
                    break

    if d.get("year"):
        try:
            y = int(d["year"])
            y_end = int(d["year_end"]) if d.get("year_end") else None
            if y_end and y_end != y:
                out["year_range"] = tuple(sorted((y, y_end)))
            else:
                out["year"] = y
        except (TypeError, ValueError):
            pass

    if isinstance(d.get("average"), bool):
        out["average"] = d["average"]

    return out

# =====================================
# QUERIES
# =====================================

def q_premium(age, si, companies, family=False):
    adults, children = (2, 2) if family else (1, 0)

    sql = """SELECT c.company_name, p.product_name, pr.age,
       pr.sum_insured, pr.premium_amount, pr.city_tier
FROM business.PREMIUM pr
JOIN business.PRODUCT_MASTER p ON p.product_id = pr.product_id
JOIN business.COMPANY_MASTER c ON c.company_id = p.company_id
WHERE pr.adults = ? AND pr.children = ? AND pr.city_tier = 'Tier 1'"""
    params = [adults, children]

    if age is not None:
        sql += "\n  AND pr.age = ?"
        params.append(int(age))
    if si is not None:
        sql += "\n  AND pr.sum_insured = ?"
        params.append(int(si))
    if companies:
        sql += "\n  AND c.company_name IN (" + ",".join("?" * len(companies)) + ")"
        params += companies

    sql += "\nORDER BY pr.premium_amount"
    return pd.read_sql(sql, get_conn(), params=params), sql


def q_curve(companies, si):
    sql = """SELECT c.company_name, pr.age, pr.premium_amount
FROM business.PREMIUM pr
JOIN business.PRODUCT_MASTER p ON p.product_id = pr.product_id
JOIN business.COMPANY_MASTER c ON c.company_id = p.company_id
WHERE pr.sum_insured = ? AND pr.city_tier = 'Tier 1'
  AND pr.adults = 1 AND pr.children = 0"""
    params = [int(si)]
    if companies:
        sql += "\n  AND c.company_name IN (" + ",".join("?" * len(companies)) + ")"
        params += companies
    sql += "\nORDER BY c.company_name, pr.age"
    return pd.read_sql(sql, get_conn(), params=params), sql


def q_terms(companies, column):
    cols = column if column else (
        "waiting_period, ped_waiting, room_rent, pre_hospitalization, "
        "post_hospitalization, ambulance_cover")

    sql = f"""SELECT c.company_name, p.product_name, {cols}
FROM business.HEALTH_FEATURES h
JOIN business.PRODUCT_MASTER p ON p.product_id = h.product_id
JOIN business.COMPANY_MASTER c ON c.company_id = p.company_id"""
    params = []
    if companies:
        sql += "\nWHERE c.company_name IN (" + ",".join("?" * len(companies)) + ")"
        params += companies
    sql += "\nORDER BY c.company_name"
    return pd.read_sql(sql, get_conn(), params=params), sql


def q_metric(companies, metric, year=None, year_range=None):
    sql = """SELECT company_name, financial_year, fy_number, metric_name,
       metric_value, metric_unit
FROM business.vw_metrics_long
WHERE 1 = 1"""
    params = []

    if companies:
        sql += "\n  AND company_name IN (" + ",".join("?" * len(companies)) + ")"
        params += companies
    if metric:
        sql += "\n  AND metric_name = ?"
        params.append(metric)
    if year:
        sql += "\n  AND fy_number = ?"
        params.append(int(year))
    elif year_range:
        sql += "\n  AND fy_number BETWEEN ? AND ?"
        params += [int(year_range[0]), int(year_range[1])]

    sql += "\nORDER BY company_name, fy_number DESC"

    try:
        return pd.read_sql(sql, get_conn(), params=params), sql
    except Exception:
        return pd.DataFrame(), sql


def q_profile(companies):
    sql = """SELECT c.company_name, p.product_name,
       COUNT(pr.premium_id)          AS premium_rows,
       MIN(pr.age)                   AS min_age,
       MAX(pr.age)                   AS max_age,
       MIN(pr.sum_insured)           AS min_cover,
       MAX(pr.sum_insured)           AS max_cover,
       MIN(pr.premium_amount)        AS cheapest,
       MAX(pr.premium_amount)        AS dearest
FROM business.COMPANY_MASTER c
JOIN business.PRODUCT_MASTER p ON p.company_id = c.company_id
LEFT JOIN business.PREMIUM pr ON pr.product_id = p.product_id"""
    params = []
    if companies:
        sql += "\nWHERE c.company_name IN (" + ",".join("?" * len(companies)) + ")"
        params += companies
    sql += "\nGROUP BY c.company_name, p.product_name\nORDER BY c.company_name"
    return pd.read_sql(sql, get_conn(), params=params), sql

# =====================================
# GLOSSARY — a fixed table, not generated text
# =====================================

GLOSSARY = {
    "sum insured": "The maximum the insurer pays in a policy year. A 10 lakh "
                   "sum insured covers claims up to Rs 10,00,000.",
    "premium": "What you pay the insurer, usually yearly, to keep the policy "
               "active.",
    "waiting period": "A stretch at the start of a policy when certain claims "
                      "are not payable. Most policies have 30 days generally, "
                      "with longer periods for specific conditions.",
    "ped": "Pre-Existing Disease — a condition you already had when you bought "
           "the policy. Usually covered only after three to four years.",
    "room rent": "A cap on the daily hospital room charge the insurer pays. "
                 "'At actuals' means no rupee cap.",
    "co-payment": "A share of each claim you pay yourself. A 20% co-pay on a "
                  "Rs 1,00,000 claim means you pay Rs 20,000.",
    "restoration": "The sum insured topped back up after it is used, so a "
                   "second illness in the same year is still covered.",
    "no claim bonus": "An increase in your sum insured, at no extra premium, "
                      "for each claim-free year.",
    "ncb": "No Claim Bonus — extra cover added free for each claim-free year.",
    "opd": "Out-Patient Department — doctor visits and tests without being "
           "admitted. Often excluded from base cover.",
    "ayush": "Treatment under Ayurveda, Yoga, Unani, Siddha and Homeopathy.",
    "day care": "Procedures needing under 24 hours in hospital, such as "
                "cataract surgery.",
    "domiciliary": "Treatment at home that would normally need hospitalisation.",
    "combined ratio": "Claims plus expenses as a percentage of premiums earned. "
                      "Below 100% means the insurer profits on underwriting.",
    "solvency ratio": "Capital held against the regulatory minimum. IRDAI "
                      "requires at least 1.5x.",
    "icr": "Incurred Claims Ratio — claims paid as a percentage of premiums.",
    "gwp": "Gross Written Premium — total premium written in the year.",
    "gdpi": "Gross Direct Premium Income — premium from direct business.",
    "roe": "Return on Equity — profit as a percentage of shareholders' funds.",
    "roa": "Return on Assets — profit as a percentage of total assets.",
    "floater": "One shared sum insured covering the whole family.",
    "tier": "City grouping used for pricing. Metros usually cost more.",
    "cover": "Another word for sum insured — the amount you are insured for.",
}


def glossary_lookup(text):
    t = (text or "").lower()
    for term, meaning in sorted(GLOSSARY.items(), key=lambda x: -len(x[0])):
        if re.search(rf"\b{re.escape(term)}\b", t):
            return term, meaning
    return None, None

# =====================================
# LOGGING
# =====================================

def log_query(question, intent, source, answered):
    try:
        row = pd.DataFrame([{
            "ts": datetime.now().isoformat(timespec="seconds"),
            "question": question,
            "intent": intent,
            "routed_by": source,
            "answered": answered,
        }])
        try:
            with open(LOG_PATH, "r", encoding="utf-8"):
                header = False
        except FileNotFoundError:
            header = True
        row.to_csv(LOG_PATH, mode="a", index=False, header=header,
                   encoding="utf-8")
    except Exception:
        pass

# =====================================
# UI
# =====================================

st.set_page_config(page_title="Insurance Assistant", layout="wide")
st.title("Health insurance assistant")
st.caption("Every answer is a database lookup. Nothing here is generated.")

slabs = load_slabs()
slab_text = ", ".join(
    f"{s/10000000:g}Cr" if s >= 10000000 else f"{s/100000:g}L" for s in slabs)
age_lo, age_hi = load_age_range()

with st.sidebar:
    st.subheader("Try asking")
    st.markdown("""
**Premiums**
- Premium for a 40 year old at 10L
- Cheapest cover at 5L for a 30 year old
- Compare ABHI and HDFC ERGO at 10L

**Policy terms**
- ABHI waiting period
- Room rent limit for Star Health
- Does Tata AIG cover maternity

**Company financials**
- ABHI GWP
- Solvency ratio for all insurers
- ICICI Lombard ROE

**Definitions**
- What does sum insured mean?
- What is a combined ratio?
    """)
    st.divider()
    st.caption(f"Cover slabs: {slab_text}")
    st.caption(f"Ages: {age_lo}–{age_hi}")
    st.caption("Tier 1 · individual cover unless a floater is asked for")

if "messages" not in st.session_state:
    st.session_state.messages = []

for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
        if m.get("table") is not None:
            st.dataframe(m["table"], hide_index=True, use_container_width=True)

question = st.chat_input("Ask a question")

if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):

        table = None
        sql_shown = None
        answered = True

        plan = route(question)
        kind = plan.get("intent")
        companies = plan.get("companies") or []
        age = plan.get("age")
        si = plan.get("sum_insured")
        family = plan.get("family", False)

        # ---------- PREMIUM ----------
        if kind == "premium":

            if age is None and si is None:
                answer = (f"I need an age or a cover amount. For example: "
                          f"*premium for a 40 year old at 10L*. "
                          f"Slabs available: {slab_text}.")
                st.markdown(answer)
                answered = False

            elif age is not None and not (age_lo <= age <= age_hi):
                answer = (f"I'm sorry — I only hold premiums for ages "
                          f"{age_lo} to {age_hi}, so age {age} isn't "
                          f"something I can answer.")
                st.markdown(answer)
                answered = False

            else:
                snapped = nearest_slab(si) if si else None
                df, sql_shown = q_premium(age, snapped, companies, family)

                if df.empty:
                    answer = NO_DATA
                    if family:
                        answer = ("I'm sorry — I only hold family floater "
                                  "rates for a few insurers. Try asking for "
                                  "individual cover instead.")
                    st.markdown(answer)
                    answered = False
                else:
                    d = df.copy()
                    d["Cover"] = d["sum_insured"].map(
                        lambda x: f"{x/10000000:g} Cr" if x >= 10000000
                        else f"{x/100000:g} L")
                    d["Premium"] = d["premium_amount"].map(
                        lambda x: f"Rs {int(x):,}")
                    table = d[["company_name", "product_name", "age",
                               "Cover", "Premium"]].rename(columns={
                        "company_name": "Insurer",
                        "product_name": "Product", "age": "Age"})

                    cheap, dear = d.iloc[0], d.iloc[-1]
                    bits = [f"**{cheap['company_name']}** is cheapest at "
                            f"Rs {int(cheap['premium_amount']):,}."]
                    if len(d) > 1:
                        gap = int(dear["premium_amount"] - cheap["premium_amount"])
                        avg_premium = d["premium_amount"].mean()
                        bits.append(
                            f"Across {len(d)} insurers the spread is "
                            f"Rs {gap:,}, with {dear['company_name']} dearest "
                            f"at Rs {int(dear['premium_amount']):,}. Average "
                            f"premium: Rs {avg_premium:,.0f}.")
                    if snapped and si and abs(snapped - si) > 1:
                        bits.append(f"(Nearest slab held: "
                                    f"{snapped/100000:g}L.)")

                    answer = " ".join(bits)
                    st.markdown(answer)
                    st.dataframe(table, hide_index=True,
                                 use_container_width=True)

                    if len(companies) > 1 and snapped:
                        cdf, _ = q_curve(companies, snapped)
                        if not cdf.empty:
                            fig = px.line(
                                cdf, x="age", y="premium_amount",
                                color="company_name",
                                labels={"age": "Age",
                                        "premium_amount": "Premium (Rs)",
                                        "company_name": "Insurer"},
                                title=f"Premium by age at {snapped/100000:g}L")
                            st.plotly_chart(fig, use_container_width=True)

        # ---------- POLICY TERMS ----------
        elif kind == "terms":
            col = plan.get("term_col")
            label = plan.get("term_label")
            df, sql_shown = q_terms(companies, col)

            if df.empty:
                answer = NO_DATA
                st.markdown(answer)
                answered = False
            else:
                table = df
                if col and label:
                    parts = []
                    for _, r in df.iterrows():
                        v = r[col]
                        if pd.isna(v):
                            shown = "not recorded"
                        elif col in BOOLEAN_COLUMNS:
                            shown = "yes" if int(v) == 1 else "no"
                        else:
                            shown = str(v)
                        parts.append(f"**{r['company_name']}** {shown}")
                    answer = f"{label.capitalize()} — " + "; ".join(parts) + "."
                else:
                    answer = "Policy terms held:"
                st.markdown(answer)
                st.dataframe(table, hide_index=True, use_container_width=True)

        # ---------- COMPANY FINANCIALS ----------
        elif kind == "metric":
            metric = plan.get("metric")
            year = plan.get("year")
            year_range = plan.get("year_range")
            avg_wanted = plan.get("average")
            df, sql_shown = q_metric(companies, metric, year, year_range)

            if df.empty:
                answer = NO_DATA
                st.markdown(answer)
                answered = False
            else:
                table = df.head(60)
                unit_mode = df["metric_unit"].mode()
                unit = unit_mode.iat[0] if not unit_mode.empty else ""

                if avg_wanted and metric:
                    grp = (df.groupby("company_name")["metric_value"]
                             .agg(["mean", "count"]).reset_index()
                             .rename(columns={"mean": "avg_value",
                                               "count": "years"}))
                    span = (f"FY{df['fy_number'].min() % 100:02d}–"
                            f"FY{df['fy_number'].max() % 100:02d}"
                            if df["fy_number"].nunique() > 1
                            else df["financial_year"].iloc[0])

                    if len(grp) == 1:
                        r = grp.iloc[0]
                        answer = (f"**Average {metric} for {r['company_name']}** "
                                  f"— {r['avg_value']:,.2f} {unit}, averaged "
                                  f"over {int(r['years'])} year(s) ({span}).")
                    else:
                        parts = [f"{r['company_name']}: {r['avg_value']:,.2f} {unit}"
                                 for _, r in grp.iterrows()]
                        answer = (f"**Average {metric} ({span})** — " +
                                  "; ".join(parts) + ".")

                    table = grp.rename(columns={
                        "company_name": "Insurer",
                        "avg_value": f"Avg {metric}",
                        "years": "Years"})

                elif metric and (year or year_range):
                    span = (f"FY{year % 100:02d}" if year else
                            f"FY{year_range[0] % 100:02d}–"
                            f"FY{year_range[1] % 100:02d}")
                    parts = [f"{r['company_name']}: {r['metric_value']:,.2f} {r['metric_unit']}"
                             for _, r in df.sort_values("company_name").iterrows()]
                    answer = f"**{metric} in {span}** — " + "; ".join(parts) + "."

                elif metric and len(companies) == 1:
                    latest = df.sort_values("fy_number", ascending=False)
                    top = latest.iloc[0]
                    answer = (f"**{top['company_name']} {metric}** — "
                              f"{top['metric_value']:,.2f} {top['metric_unit']} "
                              f"in {top['financial_year']}. "
                              f"{len(df)} years held.")
                elif metric:
                    answer = f"{metric} across {df['company_name'].nunique()} insurers:"
                else:
                    answer = f"{len(df)} figures held:"

                st.markdown(answer)
                st.dataframe(table, hide_index=True, use_container_width=True)

                if metric and df["financial_year"].nunique() > 1:
                    fig = px.line(
                        df.sort_values("fy_number"),
                        x="financial_year", y="metric_value",
                        color="company_name", markers=True,
                        labels={"financial_year": "Financial year",
                                "metric_value": metric,
                                "company_name": "Insurer"})
                    st.plotly_chart(fig, use_container_width=True)

        # ---------- COMPANY PROFILE ----------
        elif kind == "profile":
            df, sql_shown = q_profile(companies)
            if df.empty:
                answer = NO_DATA
                st.markdown(answer)
                answered = False
            else:
                d = df.copy()
                d["Cover range"] = d.apply(
                    lambda r: f"{r['min_cover']/100000:g}L – "
                              f"{r['max_cover']/100000:g}L"
                    if pd.notna(r["min_cover"]) else "no premium data", axis=1)
                d["Age range"] = d.apply(
                    lambda r: f"{int(r['min_age'])}–{int(r['max_age'])}"
                    if pd.notna(r["min_age"]) else "—", axis=1)
                table = d[["company_name", "product_name", "premium_rows",
                           "Age range", "Cover range"]].rename(columns={
                    "company_name": "Insurer", "product_name": "Product",
                    "premium_rows": "Rates held"})
                answer = "Here's what I hold:"
                st.markdown(answer)
                st.dataframe(table, hide_index=True, use_container_width=True)

        # ---------- DEFINITIONS ----------
        elif kind == "glossary":
            term, meaning = glossary_lookup(question)
            if term:
                answer = f"**{term.title()}** — {meaning}"
                st.markdown(answer)
            else:
                answer = ("I'm sorry — that term isn't in my glossary. I can "
                          "explain sum insured, waiting period, PED, room "
                          "rent, co-payment, restoration, NCB, OPD, AYUSH, "
                          "day care, combined ratio, solvency ratio, GWP "
                          "and ROE.")
                st.markdown(answer)
                answered = False

        # ---------- NOTHING MATCHED ----------
        else:
            answer = NO_DATA
            st.markdown(answer)
            answered = False

        if sql_shown and answered:
            with st.expander("The query behind this answer"):
                st.code(sql_shown, language="sql")

        log_query(question, kind, plan.get("source"), answered)
        st.session_state.messages.append(
            {"role": "assistant", "content": answer, "table": table})