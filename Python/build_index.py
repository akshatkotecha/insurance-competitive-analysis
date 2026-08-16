"""
Build the vector index for the insurance chatbot.

Reads clean.PDF_TEXT_CLEAN, chunks it, embeds it, and saves a FAISS index
to disk. Run once, and again whenever the cleaning stage is re-run.

    python build_index.py

Only Brochure and Prospectus pages are indexed — annual reports are
financial filings and would pull the retriever toward accounting language
when someone asks what a waiting period is.
"""

import os
import pickle

import pyodbc
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError:
    from langchain.text_splitter import RecursiveCharacterTextSplitter

INDEX_DIR = r"C:\Users\aksha\OneDrive\Desktop\insurance\vectorstore"
DOC_TYPES = ("Brochure", "Prospectus")

# MUST match EMBED_MODEL in chatbot.py. Vectors from different models
# are not comparable, so a mismatch gives silently wrong retrieval rather
# than an error.
EMBED_MODEL = "BAAI/bge-base-en-v1.5"      # 768-dim, ~440 MB

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 200

conn = pyodbc.connect(
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=AKSHAT\\SQLEXPRESS;"
    "DATABASE=INSURANCEDB;"
    "Trusted_Connection=yes;"
)
cursor = conn.cursor()

print("Loading cleaned pages...")

placeholders = ",".join("?" for _ in DOC_TYPES)
cursor.execute(f"""
    SELECT c.clean_text, r.company_name, r.document_type, r.page_number,
           p.product_name
    FROM clean.PDF_TEXT_CLEAN c
    JOIN raw.PDF_TEXT_RAW r ON r.pdf_id = c.pdf_id
    JOIN business.COMPANY_MASTER cm ON cm.company_name = r.company_name
    LEFT JOIN business.PRODUCT_MASTER p ON p.company_id = cm.company_id
    WHERE r.document_type IN ({placeholders})
    ORDER BY r.company_name, r.page_number
""", *DOC_TYPES)

rows = cursor.fetchall()
cursor.close()
conn.close()

print(f"  {len(rows)} pages")

splitter = RecursiveCharacterTextSplitter(
    chunk_size=CHUNK_SIZE,
    chunk_overlap=CHUNK_OVERLAP,
    separators=["\n\n", "\n", ". ", " ", ""],
)

docs = []
for text, company, doc_type, page, product in rows:
    if not text or len(text) < 100:
        continue
    for chunk in splitter.split_text(text):
        # the company name goes INTO the text, not just the metadata —
        # otherwise "what does HDFC cover" retrieves chunks that never
        # mention HDFC and the model cannot tell whose policy it is reading
        body = f"[{company} — {product or 'product'}] {chunk}"
        docs.append(Document(
            page_content=body,
            metadata={
                "company": company,
                "product": product or "",
                "doc_type": doc_type,
                "page": page,
            },
        ))

print(f"  {len(docs)} chunks")

print(f"Embedding with {EMBED_MODEL}")
print("  (first run downloads the model, a few minutes)")
embeddings = HuggingFaceEmbeddings(model_name=EMBED_MODEL)

store = FAISS.from_documents(docs, embeddings)

os.makedirs(INDEX_DIR, exist_ok=True)
store.save_local(INDEX_DIR)

with open(os.path.join(INDEX_DIR, "stats.pkl"), "wb") as f:
    pickle.dump({"pages": len(rows), "chunks": len(docs),
                 "model": EMBED_MODEL}, f)

print(f"\nSaved to {INDEX_DIR}")
print(f"  {len(rows)} pages, {len(docs)} chunks, {EMBED_MODEL}")
print("Run chatbot.py next.")