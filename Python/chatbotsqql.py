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
    pip install streamlit plotly pyodbc pandas
    ollama pull qwen2.5:3b        (optional — the bot works without it)
"""

import json
import re
from datetime import datetime

import pandas as pd
import plotly.express as px
import pyodbc
import streamlit as st

try:
    import ollama
    LLM_AVAILABLE = True
except ImportError:
    LLM_AVAILABLE = False

# =====================================
# CONFIG
# =====================================

LOG_PATH = r"C:\Users\aksha\OneDrive\Desktop\insurance\chatbot_log.csv"
MODEL = "qwen2.5:3b"

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
    t = question.lower()

    plan = {"companies": companies, "age": age, "sum_insured": si,
            "metric": metric, "term_col": term_col, "term_label": term_label,
            "family": family, "source": "rules"}

    asks_definition = bool(re.search(
        r"\b(what is|what does|what's|meaning of|mean by|explain|define)\b", t))

    # a number or a price word means they want a premium
    price_signal = any(w in t for w in PREMIUM_WORDS)

    if price_signal or (age is not None and si is not None):
        plan["intent"] = "premium"
        return plan

    # a named metric wins over a definition: "ABHI GWP" wants the figure,
    # not the meaning of GWP
    if metric and (companies or not asks_definition):
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


INTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string",
                   "enum": ["premium", "terms", "metric", "glossary",
                            "profile", "unclear"]},
        "age": {"type": "integer"},
        "sum_insured_lakhs": {"type": "number"},
    },
    "required": ["intent"],
}


def ask_model(question):
    if not LLM_AVAILABLE:
        return None
    prompt = f"""Classify this health insurance question.

premium  — asking a price
terms    — asking a policy term or whether something is covered
metric   — asking a company financial figure
glossary — asking what a word means
profile  — asking generally about one insurer
unclear  — none of these

Question: {question}
"""
    try:
        resp = ollama.chat(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            format=INTENT_SCHEMA,
            options={"temperature": 0},
        )
        d = json.loads(resp["message"]["content"])
        out = {"intent": d.get("intent")}
        if d.get("age"):
            out["age"] = d["age"]
        if d.get("sum_insured_lakhs"):
            out["sum_insured"] = int(d["sum_insured_lakhs"] * 100000)
        return out
    except Exception:
        return None

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


def q_metric(companies, metric):
    sql = """SELECT company_name, financial_year, metric_name,
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
                        bits.append(
                            f"Across {len(d)} insurers the spread is "
                            f"Rs {gap:,}, with {dear['company_name']} dearest "
                            f"at Rs {int(dear['premium_amount']):,}.")
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
            df, sql_shown = q_metric(companies, metric)

            if df.empty:
                answer = NO_DATA
                st.markdown(answer)
                answered = False
            else:
                table = df.head(60)
                latest = df.sort_values("financial_year", ascending=False)

                if metric and len(companies) == 1:
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
                        df.sort_values("financial_year"),
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