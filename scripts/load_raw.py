"""Phase 1 step 3: load raw source CSVs into Postgres as raw_* tables, unmodified."""
import os

import pandas as pd
from sqlalchemy import text

from db import get_engine

RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw")
SQL_DIR = os.path.join(os.path.dirname(__file__), "..", "sql")

TABLES = {
    "asset_registry_raw.csv": "raw_asset_registry",
    "service_tickets_raw.csv": "raw_service_tickets",
    "telemetry_raw.csv": "raw_telemetry",
    "warranty_claims_raw.csv": "raw_warranty_claims",
}


def main():
    engine = get_engine()

    with engine.begin() as conn:
        with open(os.path.join(SQL_DIR, "01_raw_schema.sql")) as f:
            conn.execute(text(f.read()))
    print("Raw schema created.")

    for csv_name, table_name in TABLES.items():
        path = os.path.join(RAW_DIR, csv_name)
        # Load as strings — the raw layer should not silently coerce types.
        df = pd.read_csv(path, dtype=str, keep_default_na=True)
        df.to_sql(table_name, engine, if_exists="append", index=False, chunksize=5000)
        print(f"Loaded {len(df):>8} rows -> {table_name}")


if __name__ == "__main__":
    main()
