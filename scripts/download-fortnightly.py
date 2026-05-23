#!/usr/bin/env python3
"""Download ALL NNDSS fortnightly report Excel files from cdc.gov.au.

Scrapes the paginated collection page to find all publication URLs,
then downloads the xlsx file from each one. Saves to data/fortnightly/.

Usage:
    python scripts/download-fortnightly.py
    python scripts/download-fortnightly.py --output-dir /path/to/dir
"""

import argparse
import os
import re
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

BASE = "https://www.cdc.gov.au"
COLLECTION = "/resources/collections/nndss-fortnightly-reports"
DEFAULT_OUTPUT = "agents/nndss-mcp-server/data/fortnightly"


def get_report_pages() -> list[str]:
    """Scrape all fortnightly report publication URLs from the collection."""
    seen = set()
    pages = []

    for page_num in range(50):
        url = f"{BASE}{COLLECTION}?page={page_num}"
        try:
            resp = urlopen(Request(url), timeout=30)
            html = resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            print(f"  Page {page_num}: {e}")
            break

        links = re.findall(
            r'href="(/resources/publications/[^"]*fortnightly[^"]*)"', html, re.I
        )
        new = [l for l in links if l not in seen]
        if not new:
            break

        for l in new:
            seen.add(l)
            pages.append(l)

        print(f"  Page {page_num}: {len(new)} new ({len(seen)} total)")
        time.sleep(0.5)

    return sorted(seen)


def get_xlsx_url(page_path: str) -> str | None:
    """Extract the xlsx download URL from a publication page."""
    url = f"{BASE}{page_path}"
    try:
        resp = urlopen(Request(url), timeout=30)
        html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"    Error fetching {page_path}: {e}")
        return None

    match = re.search(r'href="(/[^"]*\.xlsx[^"]*)"', html, re.I)
    if match:
        return match.group(1)
    return None


def download_file(url_path: str, output_dir: Path, index: int) -> Path | None:
    """Download a file from cdc.gov.au."""
    url = f"{BASE}{url_path}"
    filename = url_path.split("/")[-1]
    # Sanitise filename
    filename = re.sub(r"[^a-zA-Z0-9._-]", "_", filename)
    # Prefix with index for ordering
    out_path = output_dir / f"{index:03d}_{filename}"

    if out_path.exists() and out_path.stat().st_size > 0:
        return out_path

    try:
        resp = urlopen(Request(url), timeout=60)
        data = resp.read()
        out_path.write_bytes(data)
        return out_path
    except Exception as e:
        print(f"    Download failed: {e}")
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("Step 1: Finding all fortnightly report pages...")
    pages = get_report_pages()
    print(f"Found {len(pages)} report pages\n")

    print("Step 2: Finding xlsx download URLs...")
    downloads = []
    for i, page in enumerate(pages):
        xlsx_url = get_xlsx_url(page)
        if xlsx_url:
            downloads.append((page, xlsx_url))
            print(f"  [{i+1}/{len(pages)}] {page.split('/')[-1][:60]} → {xlsx_url.split('/')[-1][:40]}")
        else:
            print(f"  [{i+1}/{len(pages)}] {page.split('/')[-1][:60]} → NO XLSX FOUND")
        time.sleep(0.3)

    print(f"\nFound {len(downloads)} xlsx files to download\n")

    print("Step 3: Downloading xlsx files...")
    downloaded = []
    for i, (page, xlsx_url) in enumerate(downloads):
        path = download_file(xlsx_url, output_dir, i)
        if path:
            size = path.stat().st_size
            downloaded.append(path)
            print(f"  [{i+1}/{len(downloads)}] {path.name} ({size/1024:.0f} KB)")
        else:
            print(f"  [{i+1}/{len(downloads)}] FAILED: {xlsx_url}")
        time.sleep(0.3)

    print(f"\nDone: {len(downloaded)}/{len(downloads)} files downloaded to {output_dir}")
    print(f"Total size: {sum(f.stat().st_size for f in downloaded) / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    main()
