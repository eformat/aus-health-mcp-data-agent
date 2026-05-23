#!/usr/bin/env python3
"""Load NNDSS Excel data into Trino Iceberg tables.

Reads the 4 NNDSS Excel files (from local data/ or S3), normalises them,
and batch-inserts into lakehouse.nndss.notifications. Then creates
pre-aggregated views for common queries.

Usage:
    python scripts/load-nndss-trino.py

Environment variables:
    TRINO_HOST      Trino coordinator host (default: localhost)
    TRINO_PORT      Trino coordinator port (default: 8080)
    DATA_DIR        Local path to Excel files (default: agents/nndss-mcp-server/data)
"""

import os
import sys

import pandas as pd
from trino.dbapi import connect

TRINO_HOST = os.environ.get("TRINO_HOST", "localhost")
TRINO_PORT = int(os.environ.get("TRINO_PORT", "8080"))
DATA_DIR = os.environ.get("DATA_DIR", "agents/nndss-mcp-server/data")

DISEASE_FORMAL = {
    "influenza": "Influenza (laboratory confirmed)",
    "meningococcal": "Invasive meningococcal disease",
    "pneumococcal": "Invasive pneumococcal disease",
    "salmonellosis": "Salmonellosis",
}


def parse_excel(path: str, disease: str) -> pd.DataFrame:
    """Parse NNDSS Excel file and normalise to (year, state, disease, notifications)."""
    xl = pd.ExcelFile(path)
    sheets = []
    for sheet in xl.sheet_names:
        df = pd.read_excel(path, sheet_name=sheet, header=1)
        col_lower = {str(c).lower() for c in df.columns}
        has_known = any(
            k in col_lower for k in ("state", "year", "week ending (friday)")
        )
        if not has_known:
            df = pd.read_excel(path, sheet_name=sheet, header=0)
        sheets.append(df)
    raw = pd.concat(sheets, ignore_index=True)
    raw.columns = [str(c).strip() for c in raw.columns]

    cols = {c.lower(): c for c in raw.columns}

    year_col = None
    for candidate in ["year", "notification year"]:
        if candidate in cols:
            year_col = cols[candidate]
            break

    state_col = None
    for candidate in ["state", "jurisdiction"]:
        if candidate in cols:
            state_col = cols[candidate]
            break

    week_col = None
    for candidate in ["week ending (friday)", "week ending", "notification date"]:
        if candidate in cols:
            week_col = cols[candidate]
            break

    if year_col is None and week_col is not None:
        raw["_year"] = pd.to_datetime(raw[week_col], dayfirst=True, errors="coerce").dt.year
        year_col = "_year"

    if year_col is None or state_col is None:
        print(f"  WARNING: could not find year/state columns for {disease}")
        return pd.DataFrame(columns=["year", "state", "disease", "notifications"])

    grouped = (
        raw.dropna(subset=[year_col])
        .groupby([year_col, state_col])
        .size()
        .reset_index(name="notifications")
    )
    grouped.columns = ["year", "state", "notifications"]
    grouped["year"] = grouped["year"].astype(int)
    grouped["state"] = grouped["state"].astype(str).str.strip().str.upper()
    grouped["disease"] = DISEASE_FORMAL.get(disease, disease)
    grouped = grouped[(grouped["year"] >= 2000) & (grouped["year"] <= 2030)]

    return grouped.sort_values(["year", "state"]).reset_index(drop=True)


def main():
    print(f"Connecting to Trino at {TRINO_HOST}:{TRINO_PORT}")
    conn = connect(host=TRINO_HOST, port=TRINO_PORT, user="admin",
                   catalog="lakehouse", schema="nndss")
    cur = conn.cursor()

    # Create schema and table
    print("Creating schema and table...")
    cur.execute("CREATE SCHEMA IF NOT EXISTS lakehouse.nndss")
    cur.execute("DROP TABLE IF EXISTS lakehouse.nndss.notifications")
    cur.execute("""
        CREATE TABLE lakehouse.nndss.notifications (
            year INTEGER,
            state VARCHAR,
            disease VARCHAR,
            notifications INTEGER
        )
    """)

    # Load and insert data for each disease
    total_rows = 0
    for disease in ["influenza", "meningococcal", "pneumococcal", "salmonellosis"]:
        path = os.path.join(DATA_DIR, f"{disease}.xlsx")
        if not os.path.exists(path):
            print(f"  SKIP: {path} not found")
            continue

        print(f"  Loading {disease}...")
        df = parse_excel(path, disease)
        if df.empty:
            print(f"  WARNING: no data for {disease}")
            continue

        # Batch insert
        batch_size = 500
        for start in range(0, len(df), batch_size):
            batch = df.iloc[start:start + batch_size]
            values = ", ".join(
                f"({int(row.year)}, '{row.state}', '{row.disease}', {int(row.notifications)})"
                for _, row in batch.iterrows()
            )
            cur.execute(f"INSERT INTO lakehouse.nndss.notifications VALUES {values}")

        total_rows += len(df)
        print(f"  Inserted {len(df)} rows for {disease}")

    print(f"\nTotal: {total_rows} rows inserted")

    # Verify
    cur.execute("SELECT disease, COUNT(*), SUM(notifications) FROM lakehouse.nndss.notifications GROUP BY disease")
    print("\nVerification:")
    for row in cur.fetchall():
        print(f"  {row[0]}: {row[1]} rows, {row[2]} total notifications")

    # Verify with a state comparison query (Nessie doesn't support views,
    # so we query the base table directly — the agent will do the same)
    cur.execute("""
        SELECT n.disease, n.state, n.year, n.notifications,
               t.total_notifications,
               ROUND(100.0 * n.notifications / t.total_notifications, 1) AS pct_of_national
        FROM lakehouse.nndss.notifications n
        JOIN (
            SELECT disease, year, SUM(notifications) AS total_notifications
            FROM lakehouse.nndss.notifications
            GROUP BY disease, year
        ) t ON n.disease = t.disease AND n.year = t.year
        WHERE n.year = 2023 AND n.disease = 'Influenza (laboratory confirmed)'
        ORDER BY n.notifications DESC
        LIMIT 5
    """)
    print("\nTop 5 states for influenza 2023:")
    for row in cur.fetchall():
        print(f"  {row[1]}: {row[3]} notifications ({row[5]}% of national)")

    print("\nDone!")
    conn.close()


if __name__ == "__main__":
    main()
