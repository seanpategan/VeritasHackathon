"""Check that every curated source and case-study URL still responds.

A 200 response does not prove the page still supports the claim; re-read pages whose content may have
changed and update `verified_on` in app/data/*.json.

Usage:  python scripts/check_links.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import requests

DATA = Path(__file__).resolve().parent.parent / "app" / "data"
UA = {"User-Agent": "Mozilla/5.0 (FieldWise link checker)"}


def main() -> int:
    urls = [(s["id"], s["url"]) for s in json.loads((DATA / "sources.json").read_text())["sources"]]
    urls += [(c["id"], c["source_url"]) for c in json.loads((DATA / "case_studies.json").read_text())["case_studies"]]
    bad = 0
    for ident, url in urls:
        try:
            r = requests.get(url, headers=UA, timeout=25, allow_redirects=True)
            status = r.status_code
        except requests.RequestException as exc:
            status = type(exc).__name__
        ok = status == 200
        bad += not ok
        print(f"{'OK ' if ok else 'BAD'} {status} {ident} {url}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
