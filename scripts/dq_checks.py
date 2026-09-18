"""
Phase 3: automated data quality / reconciliation checks.

Every check below runs against the integrated tables (never silently against
nothing) and writes one row to dq_check_log per check: what was checked, how
many rows, how many were flagged, and a sample of the flagged rows. Nothing
here filters or drops flagged rows from the target tables — the checks
observe and report, they do not clean.

Run after scripts/transform.py has populated fact_failure_events and
fact_telemetry_readings.
"""
import json
import os
import uuid
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import text

from db import get_engine

SAMPLE_SIZE = 20


def _sample(df: pd.DataFrame, n=SAMPLE_SIZE):
    if df.empty:
        return []
    return json.loads(df.head(n).to_json(orient="records", date_format="iso"))


def check_missing_component_flagged(engine):
    df = pd.read_sql(
        text("SELECT ticket_id, vin_or_unit_no, reported_date, component_flagged FROM raw_service_tickets"),
        engine,
    )
    flagged = df[df["component_flagged"].isna() | (df["component_flagged"] == "")]
    return "missing_component_flagged", "raw_service_tickets", len(df), len(flagged), _sample(flagged)


def check_orphaned_claims(engine):
    df = pd.read_sql(
        text(
            """
            SELECT event_id, asset_id, event_date, component, source_event_ids
            FROM fact_failure_events
            """
        ),
        engine,
    )
    flagged = pd.read_sql(
        text(
            """
            SELECT event_id, asset_id, event_date, component, source_event_ids
            FROM fact_failure_events
            WHERE data_quality_flag = 'orphan_claim'
            """
        ),
        engine,
    )
    return "orphaned_warranty_claims", "fact_failure_events", len(df), len(flagged), _sample(flagged)


def check_telemetry_outliers(engine):
    total = pd.read_sql(text("SELECT count(*) AS n FROM fact_telemetry_readings"), engine)["n"].iloc[0]
    flagged = pd.read_sql(
        text(
            """
            SELECT asset_id, device_id_raw, reading_ts, temperature_c, vibration_index
            FROM fact_telemetry_readings
            WHERE is_outlier = TRUE
            LIMIT 5000
            """
        ),
        engine,
    )
    # get true flagged count separately (LIMIT above is just to bound sample query cost)
    flagged_count = pd.read_sql(
        text("SELECT count(*) AS n FROM fact_telemetry_readings WHERE is_outlier = TRUE"), engine
    )["n"].iloc[0]
    return "telemetry_outliers", "fact_telemetry_readings", int(total), int(flagged_count), _sample(flagged)


def check_taxonomy_mismatch(engine):
    df = pd.read_sql(text("SELECT claim_id, component_claimed FROM raw_warranty_claims"), engine)
    mapped_codes = pd.read_sql(text("SELECT claim_component_code FROM component_taxonomy_map"), engine)[
        "claim_component_code"
    ].tolist()
    flagged = df[~df["component_claimed"].isin(mapped_codes)]
    return "taxonomy_mismatch_warranty_claims", "raw_warranty_claims", len(df), len(flagged), _sample(flagged)


def check_duplicate_tickets(engine):
    df = pd.read_sql(
        text(
            """
            SELECT ticket_id, normalize_vin_or_unit(vin_or_unit_no) AS asset_key,
                   component_flagged, reported_date
            FROM raw_service_tickets
            WHERE component_flagged IS NOT NULL
            """
        ),
        engine,
    )
    df["reported_dt"] = pd.to_datetime(df["reported_date"], errors="coerce", format="mixed")
    df = df.dropna(subset=["reported_dt"]).sort_values(["asset_key", "component_flagged", "reported_dt"])

    dup_ids = []
    for _, g in df.groupby(["asset_key", "component_flagged"]):
        g = g.sort_values("reported_dt")
        prev_dt = None
        for _, row in g.iterrows():
            if prev_dt is not None and (row["reported_dt"] - prev_dt).days <= 2:
                dup_ids.append(row["ticket_id"])
            prev_dt = row["reported_dt"]

    flagged = df[df["ticket_id"].isin(dup_ids)]
    return "duplicate_service_tickets", "raw_service_tickets", len(df), len(flagged), _sample(flagged)


CHECKS = [
    check_missing_component_flagged,
    check_orphaned_claims,
    check_telemetry_outliers,
    check_taxonomy_mismatch,
    check_duplicate_tickets,
]


def main():
    engine = get_engine()
    sql_path = os.path.join(os.path.dirname(__file__), "..", "sql", "05_dq_log_schema.sql")
    with engine.begin() as conn:
        with open(sql_path) as f:
            conn.execute(text(f.read()))

    run_id = str(uuid.uuid4())
    run_at = datetime.now(timezone.utc)
    rows = []
    for check_fn in CHECKS:
        name, table, checked, flagged, sample = check_fn(engine)
        pct = (flagged / checked * 100) if checked else 0
        print(f"[{name}] {table}: {flagged}/{checked} flagged ({pct:.1f}%)")
        rows.append(
            {
                "check_run_id": run_id,
                "check_name": name,
                "table_name": table,
                "rows_checked": checked,
                "rows_flagged": flagged,
                "run_at": run_at,
                "sample_flagged": json.dumps(sample),
            }
        )

    log_df = pd.DataFrame(rows)
    log_df.to_sql("dq_check_log", engine, if_exists="append", index=False, dtype=None)
    print(f"\nLogged {len(rows)} checks under run_id={run_id}")


if __name__ == "__main__":
    main()
