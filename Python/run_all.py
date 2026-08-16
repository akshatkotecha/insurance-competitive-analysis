"""
Run the whole insurance pipeline in order.

    python run_all.py            all four stages
    python run_all.py 3 4        only premiums and features

Stages:
    1  extract_pdf.py             download PDFs, insert pages -> raw.PDF_TEXT_RAW
    2  clean_text.py              raw -> clean.PDF_TEXT_CLEAN
    3  extract_premium.py         rate charts -> business.PREMIUM
    4  extract_health_features.py brochures -> business.HEALTH_FEATURES

Each stage is a separate script (own process), not a function import, so a
crash in one stage can't leave stray state (an open cursor, a half-built
dict) behind for the next. Stops on the first failure, since each stage
reads what the one before it wrote.
"""

import subprocess
import sys
import time
from pathlib import Path

PYTHON_DIR = Path(__file__).resolve().parent

STAGES = [
    ("1", "extract_pdf.py",               "download and store raw text"),
    ("2", "clean_text.py",                "clean text"),
    ("3", "extract_premium.py",           "rate charts -> business.PREMIUM"),
    ("4", "extract_health_features.py",   "brochures -> business.HEALTH_FEATURES"),
]


def run(script, label):
    path = PYTHON_DIR / script
    if not path.exists():
        print(f"  MISSING: {path}")
        return False

    print(f"\n{'#'*72}\n# {label}\n#   {script}\n{'#'*72}\n")
    started = time.time()

    result = subprocess.run([sys.executable, str(path)], cwd=str(PYTHON_DIR))

    elapsed = time.time() - started
    if result.returncode == 0:
        print(f"\n--- {script} finished in {elapsed:.0f}s")
        return True

    print(f"\n--- {script} FAILED (exit {result.returncode}) after {elapsed:.0f}s")
    return False


def main():
    wanted = set(sys.argv[1:]) or {n for n, _, _ in STAGES}

    to_run = [(n, s, d) for n, s, d in STAGES if n in wanted]
    if not to_run:
        print(f"No matching stages. Valid: {[n for n, _, _ in STAGES]}")
        return 1

    print("Running stages:", ", ".join(n for n, _, _ in to_run))
    overall = time.time()

    for _, script, desc in to_run:
        if not run(script, desc):
            print("\nStopping — later stages depend on this one.")
            return 1

    print(f"\n{'='*72}")
    print(f"PIPELINE COMPLETE in {time.time() - overall:.0f}s")
    print(f"{'='*72}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
