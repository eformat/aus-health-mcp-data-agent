#!/usr/bin/env python3
"""Load NNDSS fortnightly report Excel files into Trino Iceberg table.

Parses all xlsx files in data/fortnightly/, extracts disease notification
counts by state, and loads into lakehouse.nndss.fortnightly_notifications.

Each fortnightly report has a consistent structure:
  Row 2: headers — Disease group | Disease name | Disease code | ACT | NSW | NT | Qld | SA | Tas | Vic | WA | Totals...
  Row 5+: data rows with disease counts per state

Usage:
    TRINO_HOST=localhost TRINO_PORT=8090 python scripts/load-fortnightly-trino.py
    TRINO_HOST=localhost TRINO_PORT=8090 python scripts/load-fortnightly-trino.py --data-dir /path/to/fortnightly
"""

import argparse
import os
import re
from datetime import datetime
from pathlib import Path

import pandas as pd
from trino.dbapi import connect

TRINO_HOST = os.environ.get("TRINO_HOST", "localhost")
TRINO_PORT = int(os.environ.get("TRINO_PORT", "8080"))
DEFAULT_DATA_DIR = "agents/nndss-mcp-server/data/fortnightly"

STATE_COLS = ["ACT", "NSW", "NT", "Qld", "SA", "Tas", "Vic", "WA"]
STATE_NORM = {
    "ACT": "ACT", "NSW": "NSW", "NT": "NT",
    "Qld": "QLD", "QLD": "QLD",
    "SA": "SA", "Tas": "TAS", "TAS": "TAS",
    "Vic": "VIC", "VIC": "VIC", "WA": "WA",
}


def extract_period(filename: str, df: pd.DataFrame) -> tuple[str, str]:
    """Extract the reporting period start/end dates from filename or data."""
    # Try to find dates in the first few rows
    for i in range(min(5, len(df))):
        for val in df.iloc[i].values:
            s = str(val)
            if re.match(r"\d{4}-\d{2}-\d{2}", s):
                return s[:10], s[:10]

    # Try to parse from filename
    # Pattern: "27_may_to_9_june_2024" or "fn13_-_30june2025"
    name_lower = filename.lower()

    # Try "YYYY-MM-DD" in filename
    dates = re.findall(r"(\d{4})", name_lower)
    if dates:
        return f"{dates[0]}-01-01", f"{dates[-1]}-12-31"

    return "", ""


def parse_fortnightly(path: Path) -> pd.DataFrame:
    """Parse a single fortnightly report xlsx into rows."""
    try:
        df = pd.read_excel(path, sheet_name=0, header=None)
    except Exception as e:
        print(f"    Error reading {path.name}: {e}")
        return pd.DataFrame()

    # Find the header row (contains "Disease name" or state column names)
    header_row = None
    for i in range(min(10, len(df))):
        row_vals = [str(v).strip() for v in df.iloc[i].values]
        if any("Disease name" in v for v in row_vals):
            header_row = i
            break
        if any(v in ("ACT", "NSW") for v in row_vals):
            header_row = i
            break

    if header_row is None:
        print(f"    Could not find header row in {path.name}")
        return pd.DataFrame()

    # Find date rows (usually rows 3-4 contain period dates)
    period_start = ""
    period_end = ""
    for i in range(header_row + 1, min(header_row + 5, len(df))):
        for val in df.iloc[i].values:
            s = str(val).strip()
            try:
                dt = pd.to_datetime(s)
                if not period_start:
                    period_start = dt.strftime("%Y-%m-%d")
                else:
                    period_end = dt.strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                pass

    if not period_start:
        period_start, period_end = extract_period(path.name, df)

    # Re-read with the correct header
    df = pd.read_excel(path, sheet_name=0, header=header_row)
    df.columns = [str(c).strip() for c in df.columns]

    # Find state columns
    state_map = {}
    for col in df.columns:
        norm = STATE_NORM.get(col.strip())
        if norm:
            state_map[col] = norm

    if not state_map:
        print(f"    No state columns found in {path.name}: {list(df.columns)}")
        return pd.DataFrame()

    # Find disease columns
    disease_col = None
    group_col = None
    for col in df.columns:
        cl = col.lower()
        if "disease name" in cl:
            disease_col = col
        elif "disease group" in cl:
            group_col = col

    if not disease_col:
        # Fall back: first column might be group, second disease
        if len(df.columns) >= 3:
            group_col = df.columns[0]
            disease_col = df.columns[1]

    if not disease_col:
        print(f"    No disease column found in {path.name}")
        return pd.DataFrame()

    # Extract year from period
    year = 0
    if period_end:
        try:
            year = int(period_end[:4])
        except ValueError:
            pass
    elif period_start:
        try:
            year = int(period_start[:4])
        except ValueError:
            pass

    # Parse data rows
    rows = []
    current_group = ""
    for _, row in df.iterrows():
        disease = str(row.get(disease_col, "")).strip()
        if not disease or disease == "nan" or disease.startswith("Total"):
            continue

        if group_col and str(row.get(group_col, "")).strip() not in ("", "nan"):
            current_group = str(row[group_col]).strip()

        for col, state in state_map.items():
            val = row.get(col)
            try:
                notifications = int(float(val))
            except (ValueError, TypeError):
                notifications = 0

            rows.append({
                "year": year,
                "period_start": period_start,
                "period_end": period_end,
                "disease_group": current_group,
                "disease": disease,
                "state": state,
                "notifications": notifications,
                "source_file": path.name,
            })

    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR)
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    xlsx_files = sorted(data_dir.glob("*.xlsx"))
    print(f"Found {len(xlsx_files)} xlsx files in {data_dir}")

    if not xlsx_files:
        print("No files to process")
        return

    # Parse all files
    all_data = []
    for i, f in enumerate(xlsx_files):
        print(f"  [{i+1}/{len(xlsx_files)}] {f.name}")
        df = parse_fortnightly(f)
        if not df.empty:
            all_data.append(df)
            diseases = df["disease"].nunique()
            states = df["state"].nunique()
            period = df["period_end"].iloc[0] if len(df) > 0 else "?"
            print(f"    → {len(df)} rows, {diseases} diseases, {states} states, period ending {period}")

    if not all_data:
        print("No data parsed")
        return

    combined = pd.concat(all_data, ignore_index=True)
    print(f"\nTotal: {len(combined)} rows, {combined['disease'].nunique()} diseases")
    print(f"Years: {sorted(combined['year'].unique())}")
    print(f"States: {sorted(combined['state'].unique())}")

    # Connect to Trino and load
    print(f"\nConnecting to Trino at {TRINO_HOST}:{TRINO_PORT}")
    conn = connect(host=TRINO_HOST, port=TRINO_PORT, user="admin",
                   catalog="lakehouse", schema="nndss")
    cur = conn.cursor()

    print("Creating table...")
    cur.execute("DROP TABLE IF EXISTS lakehouse.nndss.fortnightly_notifications")
    cur.execute("""
        CREATE TABLE lakehouse.nndss.fortnightly_notifications (
            year INTEGER,
            period_start VARCHAR,
            period_end VARCHAR,
            disease_group VARCHAR,
            disease VARCHAR,
            state VARCHAR,
            notifications INTEGER,
            source_file VARCHAR
        )
    """)

    # Batch insert
    batch_size = 200
    total_inserted = 0
    for start in range(0, len(combined), batch_size):
        batch = combined.iloc[start:start + batch_size]
        values = ", ".join(
            f"({int(r.year)}, '{r.period_start}', '{r.period_end}', "
            f"'{r.disease_group.replace(chr(39), chr(39)+chr(39))}', "
            f"'{r.disease.replace(chr(39), chr(39)+chr(39))}', "
            f"'{r.state}', {int(r.notifications)}, "
            f"'{r.source_file.replace(chr(39), chr(39)+chr(39))}')"
            for _, r in batch.iterrows()
        )
        cur.execute(f"INSERT INTO lakehouse.nndss.fortnightly_notifications VALUES {values}")
        total_inserted += len(batch)
        if total_inserted % 2000 == 0:
            print(f"  Inserted {total_inserted}/{len(combined)} rows")

    print(f"  Inserted {total_inserted}/{len(combined)} rows total")

    # Verify
    cur.execute("""
        SELECT disease_group, COUNT(DISTINCT disease) as diseases,
               COUNT(*) as rows, SUM(notifications) as total
        FROM lakehouse.nndss.fortnightly_notifications
        GROUP BY disease_group
        ORDER BY disease_group
    """)
    print("\nVerification by disease group:")
    for row in cur.fetchall():
        print(f"  {row[0]:40} {row[1]:3} diseases, {row[2]:6} rows, {row[3]:>10,} notifications")

    conn.close()
    print("\nDone!")


if __name__ == "__main__":
    main()
