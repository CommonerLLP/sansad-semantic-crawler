#!/usr/bin/env python3
"""Patch utility for NeVA PDFs.

Scans questions.jsonl for records with pdf_urls but pdf_path=null,
downloads the PDFs, and updates the records.
"""

import json
import time
from pathlib import Path
from commoner_analyse.neva import NevaStateCrawler
from commoner_analyse.base import safe_filename_segment

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "data" / "neva" / "gujarat"
JSONL_PATH = OUT_DIR / "questions.jsonl"
PDF_DIR = OUT_DIR / "pdfs" / "questions"

def main():
    crawler = NevaStateCrawler("gujarat", "GJ", OUT_DIR, sleep=0.6)
    crawler.bootstrap()

    if not JSONL_PATH.exists():
        print(f"Error: {JSONL_PATH} not found.")
        return

    lines = JSONL_PATH.read_text(encoding="utf-8").splitlines()
    updated_lines = []
    patched_count = 0
    skipped_count = 0

    print(f"Scanning {len(lines)} records...")

    for line in lines:
        if not line.strip():
            continue
        rec = json.loads(line)
        
        # Patch if pdf_path is null but pdf_urls exists
        if rec.get("pdf_urls") and rec.get("pdf_path") is None:
            url = rec["pdf_urls"][0]
            # Generate filename same as NevaStateCrawler.run
            # rec['key'] is GJ|q|15|8|3803|1
            key_parts = rec["key"].split("|")
            if len(key_parts) >= 6:
                asm = key_parts[2]
                s_code = key_parts[3]
                date_id = key_parts[4]
                q_no = key_parts[5]
                fname = safe_filename_segment(f"GJ_{asm}_{s_code}_{date_id}_{q_no}.pdf")
            else:
                # Fallback if key format is unexpected
                fname = safe_filename_segment(url.split("/")[-1])
                if not fname.endswith(".pdf"):
                    fname += ".pdf"

            dest = PDF_DIR / fname
            print(f"Patching {rec['key']} -> {fname}...")
            
            if crawler.download_pdf(url, dest):
                rec["pdf_path"] = str(dest.relative_to(OUT_DIR))
                patched_count += 1
            else:
                print(f"  Failed to download {url}")
        
        updated_lines.append(json.dumps(rec, ensure_ascii=False))

    if patched_count > 0:
        print(f"Writing {len(updated_lines)} records back to {JSONL_PATH}...")
        JSONL_PATH.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")
    
    print(f"Done. Patched: {patched_count}, Unchanged: {len(lines) - patched_count}")

if __name__ == "__main__":
    main()
