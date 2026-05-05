#!/usr/bin/env python3
"""Insert null (empty) records into profit_data from temp-profit-data.csv."""

import csv
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "baostock.db"
CSV_PATH = Path(__file__).parent.parent / "temp-profit-data.csv"

def main():
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    inserted = 0

    with open(CSV_PATH, newline="") as f:
        reader = csv.DictReader(f)
        batch = []
        for row in reader:
            batch.append((
                row["code"],
                int(row["year"]),
                int(row["quarter"]),
                now,
            ))
            if len(batch) >= 1000:
                conn.executemany(
                    "INSERT OR REPLACE INTO profit_data "
                    "(code, year, quarter, update_time) VALUES (?, ?, ?, ?)",
                    batch,
                )
                inserted += len(batch)
                batch.clear()

        if batch:
            conn.executemany(
                "INSERT OR REPLACE INTO profit_data "
                "(code, year, quarter, update_time) VALUES (?, ?, ?, ?)",
                batch,
            )
            inserted += len(batch)

    conn.commit()

    count = conn.execute("SELECT COUNT(*) FROM profit_data WHERE roe_avg IS NULL").fetchone()[0]
    print(f"Inserted: {inserted} null records")
    print(f"Total null records in profit_data: {count}")
    conn.close()

if __name__ == "__main__":
    main()
