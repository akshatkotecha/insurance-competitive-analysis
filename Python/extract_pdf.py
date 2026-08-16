"""
Stage 1 — download each insurer's PDFs and store their text in
raw.PDF_TEXT_RAW.

    python extract_pdf.py

Reads Companies/<Insurer>/pdf_links.json for each insurer, downloads any
PDF not already on disk, extracts its text page by page with pdfplumber,
and inserts each page into raw.PDF_TEXT_RAW.

Downloading is tiered because a single method doesn't work against every
insurer's site:
    1. plain requests            fastest, works for most sites
    2. browser-fetch              a real headless Chrome session issues the
                                   fetch(), so it carries the same cookies
                                   and TLS fingerprint as a real visitor —
                                   gets past WAFs that fingerprint the
                                   requests library specifically
    3. plain Selenium download    last resort: let Chrome's own download
                                   manager save the file, for sites that
                                   only serve the PDF via a full navigation

Idempotent and safe to re-run: a (company, document type) is skipped only
when both the file on disk AND its rows in SQL already exist. If either
is missing, it re-downloads and/or re-inserts.
"""

import base64
import datetime
import json
import time
from pathlib import Path

import pdfplumber
import pyodbc
import requests
from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# =====================================
# PATHS AND LOOKUP TABLES
# =====================================

BASE_DIR = Path(__file__).resolve().parent.parent
COMPANIES_FOLDER = BASE_DIR / "Companies"
PDF_FOLDER = BASE_DIR / "PDFs"
PDF_FOLDER.mkdir(exist_ok=True)

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

# sent as the Referer header / loaded before a browser-fetch, so the
# request looks like it came from within the insurer's own site
REFERER_BY_FOLDER = {
    "HDFC_ERGO": "https://www.hdfcergo.com/",
    "ABHI": "https://www.adityabirlacapital.com/",
    "BajajAllianz": "https://www.bajajgeneralinsurance.com/",
    "ICICI_Lombard": "https://www.icicilombard.com/",
    "NivaBupa": "https://www.nivabupa.com/",
    "StarHealth": "https://www.starhealth.in/",
    "TataAIG": "https://www.tataaig.com/",
}

headers = {
    "User-Agent":
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0 Safari/537.36",
    "Accept": "application/pdf,*/*",
    "Referer": "https://www.google.com/",
}

# =====================================
# ABHI'S ANNUAL REPORT LINK NEEDS A ONE-TIME FIX
# =====================================
# ABHI (Aditya Birla) doesn't publish its own annual report — its health
# insurance arm's financials are one section inside its parent's combined
# subsidiaries report. The originally scraped pdf_links.json points at the
# wrong document, so this patches it in place before the download loop runs.

abhi_links_file = COMPANIES_FOLDER / "ABHI" / "pdf_links.json"
if abhi_links_file.exists():
    with open(abhi_links_file, "r", encoding="utf-8") as f:
        abhi_data = json.load(f)
    for pdf in abhi_data.get("pdfs", []):
        if pdf.get("type") == "AnnualReport":
            pdf["url"] = ("https://www.adityabirlacapital.com/-/media/ABCL/pdf/"
                           "Financial-reports-of-our-subsidiary-companies/"
                           "Aditya-Birla-Subsidiaries-Financial-Report-24-25_-Web-High-Reso.webp?extension=webp")
    with open(abhi_links_file, "w", encoding="utf-8") as f:
        json.dump(abhi_data, f, indent=4)

# =====================================
# SQL CONNECTION + HELPERS
# =====================================

conn = pyodbc.connect(
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=AKSHAT\\SQLEXPRESS;"
    "DATABASE=INSURANCEDB;"
    "Trusted_Connection=yes;"
)
cursor = conn.cursor()


def get_company_id(company_name):
    cursor.execute("SELECT company_id FROM business.company_master WHERE company_name = ?", company_name)
    row = cursor.fetchone()
    return row[0] if row else None


def rows_exist_in_sql(company_id, pdf_type):
    cursor.execute(
        "SELECT COUNT(*) FROM raw.PDF_TEXT_RAW WHERE company_id = ? AND document_type = ?",
        company_id, pdf_type
    )
    return cursor.fetchone()[0] > 0


def delete_old_rows(company_id, pdf_type):
    """Clears both raw and clean rows before a re-insert, so a page removed
    from a re-downloaded PDF doesn't linger as a stale row forever."""
    try:
        cursor.execute("""
            DELETE c FROM clean.PDF_TEXT_CLEAN c
            JOIN raw.PDF_TEXT_RAW r ON c.pdf_id = r.pdf_id
            WHERE r.company_id = ? AND r.document_type = ?
        """, company_id, pdf_type)
        cursor.execute(
            "DELETE FROM raw.PDF_TEXT_RAW WHERE company_id = ? AND document_type = ?",
            company_id, pdf_type
        )
        conn.commit()
    except Exception as e:
        print("Delete-old-rows failed:", e)
        conn.rollback()


def is_valid_pdf(path):
    """Cheap check: real PDFs start with %PDF-. Catches the common failure
    mode where a blocked download saves an HTML error page instead."""
    try:
        with open(path, "rb") as f:
            return f.read(5) == b"%PDF-"
    except Exception:
        return False

# =====================================
# DOWNLOAD TIER 2/3 HELPERS (SELENIUM)
# =====================================


def create_driver():
    options = webdriver.ChromeOptions()
    prefs = {
        "download.default_directory": str(PDF_FOLDER.resolve()),
        "download.prompt_for_download": False,
        "plugins.always_open_pdf_externally": True,
    }
    options.add_experimental_option("prefs", prefs)
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-extensions")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--log-level=3")
    options.add_argument(f"user-agent={headers['User-Agent']}")

    d = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    try:
        d.execute_cdp_cmd("Page.setDownloadBehavior", {
            "behavior": "allow",
            "downloadPath": str(PDF_FOLDER.resolve())
        })
    except Exception:
        pass
    return d


def wait_for_download(path, timeout=45):
    """Chrome writes a .crdownload sidecar while a download is in flight;
    the file isn't done until that sidecar is gone."""
    crdownload = path.with_suffix(path.suffix + ".crdownload")
    waited = 0
    while waited < timeout:
        if path.exists() and not crdownload.exists():
            time.sleep(1)
            return True
        time.sleep(1)
        waited += 1
    return path.exists() and not crdownload.exists()


def selenium_download(url, path):
    """Tier 3: let Chrome's own download manager fetch the file, as if a
    person had clicked the link. Slowest option, used only when tiers 1
    and 2 both fail."""
    driver = None
    try:
        driver = create_driver()
        if path.exists():
            path.unlink()
        driver.get(url)
        success = wait_for_download(path, timeout=45)
        if success and is_valid_pdf(path):
            return True
        if path.exists():
            path.unlink()
        return False
    except WebDriverException as e:
        print(f"  Selenium crashed: {getattr(e, 'msg', e)}")
        return False
    except Exception as e:
        print(f"  Selenium unexpected error: {e}")
        return False
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


def download_via_browser_fetch(url, save_path, referer):
    """
    Tier 2: loads a real browser session, then executes JS fetch() from
    inside that page's context (same cookies/fingerprint) to pull raw PDF
    bytes. Bypasses WAF blocks that target requests-library traffic
    specifically, without the overhead of a full Selenium file download.
    """
    driver = None
    try:
        options = webdriver.ChromeOptions()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")
        options.add_argument(f"user-agent={headers['User-Agent']}")

        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        driver.set_script_timeout(60)

        driver.get(referer)
        time.sleep(2)

        # fetch() runs inside the page's own JS context, so it automatically
        # carries the referer's cookies and passes the same TLS/JS
        # fingerprint checks a real visitor would
        js_fetch = """
        var callback = arguments[arguments.length - 1];
        fetch(arguments[0], {credentials: 'include'})
            .then(r => r.arrayBuffer())
            .then(buf => {
                var bytes = new Uint8Array(buf);
                var binary = '';
                for (var i = 0; i < bytes.byteLength; i++) {
                    binary += String.fromCharCode(bytes[i]);
                }
                callback(btoa(binary));
            })
            .catch(e => callback('ERROR:' + e.toString()));
        """
        result = driver.execute_async_script(js_fetch, url)

        if result.startswith("ERROR:"):
            print("  Browser-fetch JS error:", result)
            return False

        pdf_bytes = base64.b64decode(result)
        if pdf_bytes[:4] == b"%PDF":
            with open(save_path, "wb") as f:
                f.write(pdf_bytes)
            return True
        else:
            print("  Fetched content is not a valid PDF (first bytes):", pdf_bytes[:50])
            return False

    except Exception as e:
        print("  Browser-fetch error:", e)
        return False
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass

# =====================================
# PROCESS EVERY COMPANY
# =====================================

for company_folder in COMPANIES_FOLDER.iterdir():

    if not company_folder.is_dir():
        continue

    json_file = company_folder / "pdf_links.json"
    if not json_file.exists():
        print(f"Skipping {company_folder.name} (No pdf_links.json)")
        continue

    company_name = FOLDER_TO_COMPANY_NAME.get(company_folder.name, company_folder.name.replace("_", " "))
    company_id = get_company_id(company_name)
    if company_id is None:
        print(f"⚠️  '{company_name}' not found in business.company_master — skipping entire company")
        continue

    referer = REFERER_BY_FOLDER.get(company_folder.name, "https://www.google.com/")

    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    if "pdfs" not in data:
        continue

    for pdf in data["pdfs"]:
        pdf_type = pdf.get("type", "Unknown")
        url = pdf.get("url")
        if not url:
            continue

        filename = f"{company_folder.name}_{pdf_type}.pdf"
        path = PDF_FOLDER / filename

        # skip only if the file is genuinely already in place end-to-end —
        # on disk AND already reflected in SQL — otherwise fall through
        # and re-download/re-insert whatever is missing
        file_ok = path.exists() and is_valid_pdf(path)
        already_in_sql = rows_exist_in_sql(company_id, pdf_type) if file_ok else False

        if file_ok and already_in_sql:
            continue  # genuinely done, skip entirely — no output needed

        print("\n")
        print("=" * 80)
        if file_ok and not already_in_sql:
            print(f"{company_name} — {pdf_type} (file exists, missing from SQL — re-inserting)")
        else:
            print(f"{company_name} — {pdf_type} (missing, attempting download)")
        print("=" * 80)

        downloaded = file_ok

        if not downloaded:
            # ---- tier 1: plain requests ----
            try:
                response = requests.get(url, headers=headers, timeout=30, allow_redirects=True)
                content = response.content
                if content.startswith(b"%PDF") and b"<html" not in content[:500].lower():
                    with open(path, "wb") as f:
                        f.write(content)
                    downloaded = True
                    print("Downloaded using Requests")
                else:
                    print("Requests blocked or returned HTML")
            except Exception as e:
                print("Requests Error :", e)

            # ---- tier 2: browser-fetch (bypasses WAF blocks) ----
            if not downloaded:
                print("Trying browser-fetch (JS fetch inside real Chrome session)...")
                if download_via_browser_fetch(url, path, referer):
                    downloaded = True
                    print("Downloaded using browser-fetch")
                else:
                    print("Browser-fetch failed")

            # ---- tier 3: plain Selenium download (last resort) ----
            if not downloaded:
                for attempt in range(2):
                    print(f"Trying plain Selenium download (attempt {attempt+1}/2)...")
                    if selenium_download(url, path):
                        downloaded = True
                        print("Downloaded using Selenium")
                        break
                    time.sleep(3)
                if not downloaded:
                    print("All download methods failed")

        if not downloaded:
            print("Skipping PDF (could not download)")
            continue

        # ---- extract text and insert into SQL ----
        delete_old_rows(company_id, pdf_type)

        try:
            with pdfplumber.open(path) as pdf_file:
                print("Pages :", len(pdf_file.pages))
                inserted = 0
                now = datetime.datetime.now()

                for page_number, page in enumerate(pdf_file.pages, start=1):
                    text = page.extract_text()
                    if not text:
                        continue
                    text = text.strip()
                    if len(text) == 0:
                        continue

                    cursor.execute(
                        """
                        INSERT INTO raw.PDF_TEXT_RAW
                        (company_id, company_name, product_name, document_type, page_number, raw_text, extracted_on)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        company_id, company_name, None, pdf_type, page_number, text, now
                    )
                    inserted += 1

                conn.commit()
                print(f"Inserted {inserted} pages into SQL Server")

        except Exception as e:
            print("Extraction Failed")
            print(e)

# =====================================
# CLEANUP
# =====================================

try:
    cursor.close()
except Exception:
    pass
try:
    conn.close()
except Exception:
    pass

print("\n")
print("=" * 80)
print("ALL COMPANIES PROCESSED — idempotent, safe to re-run anytime")
print("=" * 80)
