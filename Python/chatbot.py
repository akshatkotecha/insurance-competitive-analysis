"""
Insurance chatbot — SQL first, retrieval as fallback.

    streamlit run chatbot.py

Design
------
Numeric questions go to parameterised SQL. Conceptual questions go to
vector search over policy text.

The ordering matters. SQL returning zero rows is an unambiguous signal, so
falling back to text is safe. Retrieval has no such signal — it always
returns its closest chunks, however irrelevant — so it can never tell you
it failed. The reliable source therefore goes first.

The model never writes SQL. It only extracts intent (age, cover, insurer)
into a fixed schema; those values go into prepared statements. A garbled
model response produces a clarifying question, not a wrong number.

Prerequisites
-------------
    pip install streamlit faiss-cpu langchain langchain-community \
                langchain-huggingface langchain-ollama plotly
    ollama pull qwen2.5:3b
    python build_index.py
"""

import json
import os
import pickle
import re
from datetime import datetime

import ollama
import pandas as pd
import plotly.express as px
import pyodbc
import streamlit as st
from langchain_community.vectorstores import FAISS
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_ollama import ChatOllama

# =====================================
# CONFIG
# =====================================

INDEX_DIR = r"C:\Users\aksha\OneDrive\Desktop\insurance\vectorstore"
LOG_PATH = r"C:\Users\aksha\OneDrive\Desktop\insurance\chatbot_log.csv"
MODEL = "qwen2.5:3b"

# MUST match EMBED_MODEL in build_index.py — vectors from different models
# are not comparable, and a mismatch degrades retrieval without erroring.
EMBED_MODEL = "BAAI/bge-base-en-v1.5"

# Fetch more chunks than are shown. With short factual questions the usual
# failure is "the right chunk ranked 7th", not "the model misread the
# question", so a wider net helps more than a bigger encoder.
RETRIEVE_K = 8
FETCH_K = 24            # candidates considered before MMR picks K
MMR_LAMBDA = 0.6        # 1.0 = pure relevance, 0 = pure diversity

CONN_STR = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=AKSHAT\\SQLEXPRESS;"
    "DATABASE=INSURANCEDB;"
    "Trusted_Connection=yes;"
)

SLAB_TEXT = "5L, 7.5L, 10L, 15L, 20L, 25L, 50L, 75L, 1Cr"

# =====================================
# RESOURCES
# =====================================

@st.cache_resource
def get_retriever():
    # the index records which model built it; a mismatch is the single most
    # confusing failure mode, so catch it loudly
    try:
        with open(os.path.join(INDEX_DIR, "stats.pkl"), "rb") as f:
            built_with = pickle.load(f).get("model")
        if built_with and built_with != EMBED_MODEL:
            st.error(
                f"Index was built with {built_with} but this app uses "
                f"{EMBED_MODEL}. Re-run build_index.py, or set EMBED_MODEL "
                f"back to {built_with}."
            )
    except FileNotFoundError:
        pass

    emb = HuggingFaceEmbeddings(model_name=EMBED_MODEL)
    store = FAISS.load_local(INDEX_DIR, emb, allow_dangerous_deserialization=True)

    # MMR rather than plain similarity: with several insurers' brochures in
    # one index, straight top-k often returns eight near-identical chunks
    # from whichever document phrases things closest to the question. MMR
    # trades a little relevance for coverage across sources.
    return store.as_retriever(
        search_type="mmr",
        search_kwargs={"k": RETRIEVE_K, "fetch_k": FETCH_K,
                       "lambda_mult": MMR_LAMBDA},
    )


@st.cache_resource
def get_rag_chain():
    """
    LCEL chain: documents -> prompt -> model -> text.
    The dict at the front runs both branches in parallel; `question` passes
    straight through while `context` goes via the retriever.
    """
    llm = ChatOllama(model=MODEL, temperature=0.1)

    prompt = ChatPromptTemplate.from_template(
        "You are explaining health insurance to someone with no prior "
        "knowledge. Answer using ONLY the context below.\n\n"
        "Rules:\n"
        "- Plain language. Expand any jargon you use.\n"
        "- If the context does not answer the question, say so plainly. "
        "Do not guess.\n"
        "- Name the insurer when the answer is specific to one policy.\n"
        "- Two or three short paragraphs at most.\n\n"
        "Context:\n{context}\n\nQuestion: {question}"
    )

    def join_docs(docs):
        # label each passage with its source so the model can attribute a
        # claim to the right insurer instead of blending several policies
        parts = []
        for d in docs:
            src = d.metadata.get("company", "?")
            page = d.metadata.get("page", "?")
            parts.append(f"[{src}, page {page}]\n{d.page_content}")
        return "\n\n---\n\n".join(parts)[:9000]

    return (
        {"context": get_retriever() | join_docs,
         "question": RunnablePassthrough()}
        | prompt
        | llm
        | StrOutputParser()
    )


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

# =====================================
# LOGGING
# =====================================

def log_query(question, route, intent, hit):
    """One line per question. After fifty you can report route hit rates."""
    try:
        row = pd.DataFrame([{
            "ts": datetime.now().isoformat(timespec="seconds"),
            "question": question,
            "route": route,
            "intent": intent,
            "found_answer": hit,
        }])
        header = False
        try:
            with open(LOG_PATH, "r", encoding="utf-8"):
                pass
        except FileNotFoundError:
            header = True
        row.to_csv(LOG_PATH, mode="a", index=False, header=header,
                   encoding="utf-8")
    except Exception:
        pass

# =====================================
# INTENT
# =====================================

INTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string",
                   "enum": ["premium", "compare", "feature", "metric",
                            "definition", "unclear"]},
        "age": {"type": "integer"},
        "sum_insured_lakhs": {"type": "number"},
        "companies": {"type": "array", "items": {"type": "string"}},
        "family": {"type": "string", "enum": ["individual", "family"]},
        "topic": {"type": "string"},
    },
    "required": ["intent"],
}

INTENT_PROMPT = """Classify this insurance question and pull out any details.

intent:
  premium    — the price for a specific age and/or cover amount
  compare    — comparing prices across insurers
  feature    — whether a policy covers something, or its terms
  metric     — company financials (GWP, ROE, solvency, market share)
  definition — what a term means, no specific policy in mind
  unclear    — cannot tell

Extract where stated:
  age                 person's age in years
  sum_insured_lakhs   cover in lakhs (1 crore = 100)
  companies           insurer names mentioned
  family              "family" if a floater is implied, else "individual"
  topic               key term or subject

Insurers: ABHI, Bajaj Allianz, Care Health, HDFC ERGO, ICICI Lombard,
Niva Bupa, Star Health, Tata AIG.

Question: {question}
"""


def classify(question):
    try:
        resp = ollama.chat(
            model=MODEL,
            messages=[{"role": "user",
                       "content": INTENT_PROMPT.format(question=question)}],
            format=INTENT_SCHEMA,
            options={"temperature": 0},
        )
        return json.loads(resp["message"]["content"])
    except Exception:
        return {"intent": "definition", "topic": question}


def match_companies(names):
    if not names:
        return []
    known = load_companies()["company_name"].unique().tolist()
    out = []
    for n in names:
        n_low = str(n).lower().strip()
        for k in known:
            if n_low in k.lower() or k.lower() in n_low:
                if k not in out:
                    out.append(k)
                break
    return out


def nearest_slab(si_lakhs):
    slabs = load_slabs()
    if not slabs or si_lakhs is None:
        return None
    target = si_lakhs * 100000
    return min(slabs, key=lambda s: abs(s - target))

# =====================================
# SQL
# =====================================

def premium_query(age, si, companies, family=False):
    """Returns (dataframe, sql_text) so the query can be shown to the user."""
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


def curve_query(companies, si):
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


def feature_query(companies, topic):
    df = pd.read_sql("""
        SELECT c.company_name, p.product_name, h.*
        FROM business.HEALTH_FEATURES h
        JOIN business.PRODUCT_MASTER p ON p.product_id = h.product_id
        JOIN business.COMPANY_MASTER c ON c.company_id = p.company_id
        ORDER BY c.company_name
    """, get_conn())

    if companies:
        df = df[df["company_name"].isin(companies)]

    if topic:
        t = topic.lower()
        keep = ["company_name", "product_name"]
        for col in df.columns:
            if col in keep or col in ("feature_id", "product_id"):
                continue
            probe = col.replace("_", " ")
            if any(w in probe for w in t.split() if len(w) > 3) or probe in t:
                keep.append(col)
        if len(keep) > 2:
            df = df[keep]

    return df


def metric_query(companies, topic):
    try:
        df = pd.read_sql("""
            SELECT company_name, financial_year, metric_name,
                   metric_value, metric_unit
            FROM business.vw_metrics_long
            ORDER BY company_name, fy_number DESC
        """, get_conn())
    except Exception:
        return pd.DataFrame()

    if companies:
        df = df[df["company_name"].isin(companies)]
    if topic:
        words = [re.escape(w) for w in topic.lower().split() if len(w) > 2]
        if words:
            hit = df["metric_name"].str.lower().str.contains("|".join(words))
            if hit.any():
                df = df[hit]
    return df

# =====================================
# GLOSSARY — deterministic, no model call
# =====================================

GLOSSARY = {
    "sum insured": "The maximum the insurer pays in a policy year. A 10 lakh "
                   "sum insured means claims are covered up to Rs 10,00,000.",
    "premium": "What you pay the insurer, usually yearly, to keep the policy "
               "active.",
    "waiting period": "A stretch at the start of a policy when certain claims "
                      "are not payable. Most policies have 30 days generally, "
                      "with longer periods for specific conditions.",
    "ped": "Pre-Existing Disease — a condition you already had when you bought "
           "the policy. Usually covered only after three to four years.",
    "room rent": "A cap on the daily hospital room charge the insurer pays. "
                 "'At actuals' means no rupee cap; a percentage cap means you "
                 "pay the excess.",
    "co-payment": "A share of each claim you pay yourself. A 20% co-pay on a "
                  "Rs 1,00,000 claim means you pay Rs 20,000.",
    "restoration": "The sum insured topped back up after it is used, so a "
                   "second illness in the same year is still covered.",
    "no claim bonus": "An increase in your sum insured, at no extra premium, "
                      "for each year you make no claim.",
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
    "icr": "Incurred Claims Ratio — claims paid as a percentage of premiums "
           "collected.",
    "gwp": "Gross Written Premium — total premium written in the year. A "
           "measure of scale.",
    "roe": "Return on Equity — profit as a percentage of shareholders' funds.",
    "floater": "One shared sum insured covering the whole family, rather than "
               "a separate amount per person.",
    "tier": "City grouping used for pricing. Metros usually cost more.",
}


def glossary_lookup(text):
    t = (text or "").lower()
    for term, meaning in sorted(GLOSSARY.items(), key=lambda x: -len(x[0])):
        if term in t:
            return term, meaning
    return None, None

# =====================================
# UI
# =====================================

st.set_page_config(page_title="Insurance Assistant", layout="wide")
st.title("Health insurance assistant")
st.caption("Prices come from the database. Explanations come from the policy "
           "documents.")

with st.sidebar:
    st.subheader("Try asking")
    st.markdown(f"""
**Prices** — looked up
- Premium for a 40 year old at 10L
- Compare ABHI and HDFC ERGO at 10L
- Cheapest cover at 5L for a 30 year old

**Policy terms** — from brochures
- What is ABHI's waiting period?
- Does Star Health cover maternity?

**Concepts** — plain explanations
- What does sum insured mean?
- What is a combined ratio?

Cover is sold in fixed slabs: {SLAB_TEXT}
    """)

    st.divider()
    st.caption("Premium rows held")
    st.dataframe(pd.read_sql("""
        SELECT c.company_name AS Insurer, COUNT(*) AS Rows
        FROM business.PREMIUM pr
        JOIN business.PRODUCT_MASTER p ON p.product_id = pr.product_id
        JOIN business.COMPANY_MASTER c ON c.company_id = p.company_id
        GROUP BY c.company_name ORDER BY c.company_name
    """, get_conn()), hide_index=True, use_container_width=True)

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
        route = "glossary"
        found = True

        term, meaning = glossary_lookup(question)
        wants_definition = any(w in question.lower()
                               for w in ["what is", "what does", "meaning",
                                         "mean by", "explain", "define"])

        if term and wants_definition:
            answer = f"**{term.title()}** — {meaning}"
            st.markdown(answer)
            log_query(question, "glossary", "definition", True)
            st.session_state.messages.append(
                {"role": "assistant", "content": answer, "table": None})

        else:
            with st.spinner("Working it out..."):
                intent = classify(question)

            companies = match_companies(intent.get("companies"))
            age = intent.get("age")
            si_lakhs = intent.get("sum_insured_lakhs")
            family = intent.get("family") == "family"
            kind = intent.get("intent")

            # ---------- PRICE ----------
            if kind in ("premium", "compare"):
                route = "sql"

                if age is None and si_lakhs is None:
                    answer = ("I need an age or a cover amount. For example: "
                              "*premium for a 40 year old at 10L*.")
                    st.markdown(answer)
                    found = False

                else:
                    snapped = nearest_slab(si_lakhs) if si_lakhs else None
                    df, sql = premium_query(age, snapped, companies, family)

                    if df.empty:
                        # SQL returning nothing is an unambiguous signal, so
                        # falling back to the documents is safe. The wording
                        # tells the user they have moved from a looked-up
                        # number to a retrieved passage.
                        route = "sql->rag"
                        st.info("Not in the rate tables — checking the documents.")

                        try:
                            text = get_rag_chain().invoke(question)
                            docs = get_retriever().invoke(question)
                        except Exception as e:
                            text, docs = f"(model unavailable: {e})", []

                        answer = (
                            f"I don't have that exact combination in the rate "
                            f"tables. Cover is sold in fixed slabs "
                            f"({SLAB_TEXT}) and not every insurer offers every "
                            f"slab at every age.\n\n"
                            f"**From the policy documents:** {text}"
                        )
                        st.markdown(answer)
                        found = False

                        if docs:
                            with st.expander("Sources"):
                                for d in docs[:3]:
                                    st.caption(f"{d.metadata.get('company')} "
                                               f"p{d.metadata.get('page')}")

                        if snapped and age is not None:
                            near, _ = premium_query(None, snapped, companies, family)
                            if not near.empty:
                                near = near.copy()
                                near["gap"] = (near["age"] - int(age)).abs()
                                near = near.nsmallest(8, "gap")
                                near["Cover"] = (near["sum_insured"] / 100000
                                                 ).astype(int).astype(str) + " L"
                                near["Premium"] = near["premium_amount"].map(
                                    lambda x: f"Rs {int(x):,}")
                                table = near[["company_name", "age", "Cover",
                                              "Premium"]].rename(columns={
                                    "company_name": "Insurer", "age": "Age"})
                                st.caption("Closest ages I do have:")
                                st.dataframe(table, hide_index=True,
                                             use_container_width=True)

                    else:
                        df = df.copy()
                        df["Cover"] = (df["sum_insured"] / 100000
                                       ).astype(int).astype(str) + " L"
                        df["Premium"] = df["premium_amount"].map(
                            lambda x: f"Rs {int(x):,}")
                        table = df[["company_name", "product_name", "age",
                                    "Cover", "Premium"]].rename(columns={
                            "company_name": "Insurer",
                            "product_name": "Product", "age": "Age"})

                        cheap, dear = df.iloc[0], df.iloc[-1]
                        bits = [f"**{cheap['company_name']}** is cheapest at "
                                f"Rs {int(cheap['premium_amount']):,}."]
                        if len(df) > 1:
                            gap = int(dear["premium_amount"] - cheap["premium_amount"])
                            bits.append(
                                f"Across {len(df)} insurers the spread is "
                                f"Rs {gap:,}, with {dear['company_name']} "
                                f"dearest at Rs {int(dear['premium_amount']):,}.")
                        if snapped and si_lakhs and abs(snapped - si_lakhs * 100000) > 1:
                            bits.append(f"(Nearest slab: {int(snapped/100000)}L.)")

                        answer = " ".join(bits)
                        st.markdown(answer)
                        st.dataframe(table, hide_index=True,
                                     use_container_width=True)

                        # age curve when the question compares insurers
                        if kind == "compare" and snapped:
                            cdf, csql = curve_query(companies, snapped)
                            if not cdf.empty:
                                fig = px.line(
                                    cdf, x="age", y="premium_amount",
                                    color="company_name",
                                    labels={"age": "Age",
                                            "premium_amount": "Premium (Rs)",
                                            "company_name": "Insurer"},
                                    title=f"Premium by age at "
                                          f"{int(snapped/100000)}L")
                                st.plotly_chart(fig, use_container_width=True)

                        with st.expander("The query behind this answer"):
                            st.code(sql, language="sql")

            # ---------- COMPANY FINANCIALS ----------
            elif kind == "metric":
                route = "sql"
                df = metric_query(companies, intent.get("topic"))
                if df.empty:
                    answer = ("No financial metrics stored for that. Run "
                              "peer_trend_views.sql if you have not yet.")
                    st.markdown(answer)
                    found = False
                else:
                    table = df.head(40)
                    answer = "Here are the figures held:"
                    st.markdown(answer)
                    st.dataframe(table, hide_index=True, use_container_width=True)

            # ---------- POLICY TERMS ----------
            elif kind == "feature":
                route = "sql+rag"
                df = feature_query(companies, intent.get("topic"))

                try:
                    text = get_rag_chain().invoke(question)
                    docs = get_retriever().invoke(question)
                except Exception as e:
                    text, docs = f"(model unavailable: {e})", []

                answer = text or "I could not find that in the documents."
                st.markdown(answer)

                if not df.empty:
                    table = df
                    st.caption("Stored feature data:")
                    st.dataframe(table, hide_index=True, use_container_width=True)

                if docs:
                    with st.expander("Sources"):
                        for d in docs[:3]:
                            st.caption(f"{d.metadata.get('company')} "
                                       f"p{d.metadata.get('page')}")
                            st.text(d.page_content[:280] + "...")

            # ---------- ANYTHING ELSE ----------
            else:
                route = "rag"
                if term:
                    answer = f"**{term.title()}** — {meaning}"
                    st.markdown(answer)
                    route = "glossary"
                else:
                    try:
                        text = get_rag_chain().invoke(question)
                        docs = get_retriever().invoke(question)
                    except Exception as e:
                        text, docs = None, []
                        st.error(f"Model unavailable: {e}")

                    answer = text or ("I could not find that in the documents. "
                                      "Try naming a specific insurer.")
                    st.markdown(answer)
                    found = bool(text)

                    if docs:
                        with st.expander("Sources"):
                            for d in docs[:3]:
                                st.caption(f"{d.metadata.get('company')} "
                                           f"p{d.metadata.get('page')}")

            log_query(question, route, kind, found)
            st.session_state.messages.append(
                {"role": "assistant", "content": answer, "table": table})