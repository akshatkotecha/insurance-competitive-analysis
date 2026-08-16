# Health Insurance Competitive Analysis

A data pipeline and two chatbots for comparing eight Indian health insurers —
ABHI, Bajaj Allianz, Care Health, HDFC ERGO, ICICI Lombard, Niva Bupa, Star
Health and Tata AIG — on premiums, policy features, and company financials.

Each insurer's brochure, prospectus, rate chart and annual report is
downloaded, parsed into a SQL Server database, and made queryable through
two Streamlit chatbots that answer the same kinds of questions with two
different architectures.

## The two chatbots

| | `Python/chatbotsqql.py` | `Python/chatbot.py` |
|---|---|---|
| Approach | SQL only | SQL first, retrieval (RAG) as fallback |
| Numeric questions (premiums, GWP, ROE...) | Parameterised SQL | Parameterised SQL |
| Conceptual / policy-wording questions | Fixed glossary + regex-matched columns | Vector search over policy PDFs, answered by a local LLM |
| Generates text? | No — every answer is a lookup | Only for questions SQL can't answer |

**Why two versions.** The SQL-only bot is fully deterministic — every
answer traces back to a row in the database, so it can never hallucinate,
but it can only answer what's already structured into a column. The
SQL+RAG bot keeps that same SQL-first rule (SQL returning zero rows is an
unambiguous "not here", so falling back to retrieval is safe), but adds a
retrieval step for anything that lives only in policy prose — "does this
plan cover maternity", "what counts as a day-care procedure" — by pulling
the relevant passage from the actual brochure and having a local model
(via [Ollama](https://ollama.com)) explain it in plain language. The
model never writes SQL and never invents numbers; it only classifies
intent and explains retrieved text.

Run either with:

```bash
streamlit run Python/chatbotsqql.py   # SQL only
streamlit run Python/chatbot.py       # SQL + RAG
```

## Pipeline

Each stage is a standalone script that reads what the previous one wrote,
so any stage can be re-run on its own once its input exists.

```
Python/extract_pdf.py       Companies/<Insurer>/pdf_links.json
                                     |  download PDFs, extract text
                                     v
                             raw.PDF_TEXT_RAW  (SQL)

Python/clean_text.py                |  normalise whitespace
                                     v
                             clean.PDF_TEXT_CLEAN  (SQL)

Python/extract_products.py          |  seed one flagship product per insurer
                                     v
                             business.PRODUCT_MASTER  (SQL)

Python/extract_premium.py           |  parse rate-chart PDFs (tables / OCR / word coords)
                                     v
                             business.PREMIUM  (SQL)

Python/extract_health_features.py   |  parse brochures for waiting periods, room rent, etc.
                                     v
                             business.HEALTH_FEATURES  (SQL)

Python/extractmetrics.ipynb         |  parse annual reports for GWP, ROE, solvency, etc.
                                     v
                             business.company_metrics  (SQL)

Python/build_index.py               |  chunk + embed brochures/prospectuses
                                     v
                             vectorstore/  (FAISS index, used by chatbot.py)
```

Run the SQL-writing stages in order with:

```bash
python Python/run_all.py            # stages 1-4
python Python/run_all.py 3 4        # only premiums and features
python Python/build_index.py        # once extraction is done, before chatbot.py
```

## Database

SQL Server, three schemas:

- **`raw`** — one row per PDF page, straight from `pdfplumber` (`PDF_TEXT_RAW`)
- **`clean`** — the same pages after whitespace normalisation (`PDF_TEXT_CLEAN`)
- **`business`** — the structured tables the chatbots query directly:
  `COMPANY_MASTER`, `PRODUCT_MASTER`, `PREMIUM`, `HEALTH_FEATURES`,
  `company_metrics` (exposed to the chatbots as the long-format view
  `vw_metrics_long`)

Schema DDL lives in [SQL/create_tables.sql](SQL/create_tables.sql) — add
your `CREATE TABLE` statements there if you're setting this up fresh; the
scripts above assume the columns each one reads/writes already exist.

Connection settings (server, database, driver) are in
[Python/config.py](Python/config.py).

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# local LLM for both chatbots' intent classification, and chatbot.py's answers
ollama pull qwen2.5:3b
```

You'll also need:
- **SQL Server** with the `ODBC Driver 17 for SQL Server` installed, and
  the schema from `SQL/create_tables.sql` applied
- **Google Chrome** (for `extract_pdf.py`'s Selenium fallback tiers)
- **Tesseract OCR** at `C:\Program Files\Tesseract-OCR\tesseract.exe`
  (only needed for ICICI Lombard's rate chart, which is image-only)

Then run the pipeline stages in order (above), followed by either
chatbot.

## Project layout

```
Python/       All pipeline stages and both chatbots
SQL/          Schema DDL and cleanup queries
Companies/    pdf_links.json per insurer — the source URLs each pipeline
              run downloads from (downloaded PDFs themselves are gitignored)
PDFs/         Rate charts used by extract_premium.py (gitignored — see below)
vectorstore/  FAISS index built by build_index.py (gitignored — regenerate it)
```

Large or regenerable folders (`PDFs/`, `Companies/*/downloaded/`,
`vectorstore/`, `.venv/`) are excluded via `.gitignore` rather than
committed — see the comments there for how to rebuild each one.
