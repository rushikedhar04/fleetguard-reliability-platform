"""
Phase 2 step 6: build fact_failure_events.

Business rule (documented in mappings.yml under fact_failure_events):
A failure event is any of — a service ticket, a telemetry reading carrying
an error_code, or a warranty claim — resolved to canonical asset_id.
Events on the SAME asset_id that fall within a 7-day window of each other
are reconciled into a single failure event, recording which source systems
contributed evidence to it.

This step also assigns the row-level data_quality_flag:
  - 'orphan_claim'        claim-only event, no ticket/telemetry support
  - 'unmapped_taxonomy'   claim component code has no canonical mapping
  - 'missing_component'   no component could be determined at all
  - 'ok'                  none of the above

Runs after sql/01-04 have created raw_*, asset_crosswalk, component_taxonomy_map.
"""
import re
from datetime import datetime

import pandas as pd
from dateutil import parser as dtparser
from sqlalchemy import text

from db import get_engine

RECONCILE_WINDOW_DAYS = 7


def parse_messy_date(s):
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return pd.NaT
    try:
        return dtparser.parse(str(s))
    except (ValueError, TypeError):
        return pd.NaT


def load_candidate_events(engine):
    tickets = pd.read_sql(
        text(
            """
            SELECT t.ticket_id AS source_id, cw.asset_id, t.reported_date AS raw_date,
                   t.component_flagged AS component, t.resolution_code
            FROM raw_service_tickets t
            JOIN asset_crosswalk cw ON normalize_vin_or_unit(t.vin_or_unit_no) = cw.vin_or_unit_no_key
            """
        ),
        engine,
    )
    tickets["source_system"] = "service_ticket"
    tickets["event_date"] = tickets["raw_date"].apply(parse_messy_date)

    telemetry = pd.read_sql(
        text(
            """
            SELECT t.device_id || '@' || t.timestamp AS source_id, cw.asset_id,
                   t.timestamp AS raw_date, t.error_code
            FROM raw_telemetry t
            JOIN asset_crosswalk cw ON normalize_device_id(t.device_id) = cw.device_id_key
            WHERE t.error_code IS NOT NULL AND t.error_code <> ''
            """
        ),
        engine,
    )
    telemetry["source_system"] = "telemetry"
    telemetry["component"] = None
    telemetry["resolution_code"] = None
    telemetry["event_date"] = telemetry["raw_date"].apply(parse_messy_date)

    claims = pd.read_sql(
        text(
            """
            SELECT c.claim_id AS source_id, cw.asset_id, c.claim_date AS raw_date,
                   c.component_claimed, tax.canonical_component
            FROM raw_warranty_claims c
            JOIN asset_crosswalk cw ON normalize_asset_serial(c.asset_serial) = cw.asset_serial_key
            LEFT JOIN component_taxonomy_map tax ON c.component_claimed = tax.claim_component_code
            """
        ),
        engine,
    )
    claims["source_system"] = "warranty_claim"
    claims["resolution_code"] = None
    claims["event_date"] = claims["raw_date"].apply(parse_messy_date)
    claims["taxonomy_unmapped"] = claims["canonical_component"].isna()
    claims["component"] = claims["canonical_component"].fillna(
        "Unmapped: " + claims["component_claimed"]
    )

    for df in (tickets, telemetry, claims):
        if "taxonomy_unmapped" not in df.columns:
            df["taxonomy_unmapped"] = False

    cols = ["source_id", "asset_id", "event_date", "component", "source_system", "taxonomy_unmapped"]
    events = pd.concat([tickets[cols], telemetry[cols], claims[cols]], ignore_index=True)
    events = events.dropna(subset=["event_date"]).sort_values(["asset_id", "event_date"])
    return events


def reconcile(events: pd.DataFrame) -> pd.DataFrame:
    """Greedy chain-clustering: within each asset, sort by date and start a
    new failure event whenever the gap to the previous event exceeds the
    reconciliation window."""
    records = []
    window = pd.Timedelta(days=RECONCILE_WINDOW_DAYS)

    for asset_id, group in events.groupby("asset_id", sort=False):
        group = group.sort_values("event_date")
        cluster_start = None
        cluster_rows = []

        def flush(asset_id, rows):
            sources = sorted(set(r["source_system"] for r in rows))
            has_ticket_or_claim_component = [
                r["component"] for r in rows if r["source_system"] != "telemetry" and r["component"]
            ]
            component = has_ticket_or_claim_component[0] if has_ticket_or_claim_component else None
            taxonomy_unmapped = any(r["taxonomy_unmapped"] for r in rows)

            if component is None:
                dq_flag = "missing_component"
            elif taxonomy_unmapped:
                dq_flag = "unmapped_taxonomy"
            elif sources == ["warranty_claim"]:
                dq_flag = "orphan_claim"
            else:
                dq_flag = "ok"

            records.append(
                {
                    "asset_id": asset_id,
                    "event_date": min(r["event_date"] for r in rows).date(),
                    "component": component or "Unclassified",
                    "source_systems_present": sources,
                    "source_event_ids": [r["source_id"] for r in rows],
                    "data_quality_flag": dq_flag,
                }
            )

        for _, row in group.iterrows():
            r = row.to_dict()
            if cluster_start is None or (r["event_date"] - cluster_start) <= window:
                cluster_rows.append(r)
                cluster_start = cluster_rows[0]["event_date"]
            else:
                flush(asset_id, cluster_rows)
                cluster_rows = [r]
                cluster_start = r["event_date"]
        if cluster_rows:
            flush(asset_id, cluster_rows)

    return pd.DataFrame(records)


def main():
    engine = get_engine()
    print("Loading candidate events from tickets, telemetry faults, and claims...")
    events = load_candidate_events(engine)
    print(f"  {len(events)} candidate events across {events['asset_id'].nunique()} assets")

    print(f"Reconciling within {RECONCILE_WINDOW_DAYS}-day windows per asset...")
    fact = reconcile(events)
    print(f"  -> {len(fact)} reconciled failure events")

    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS fact_failure_events"))
        conn.execute(
            text(
                """
                CREATE TABLE fact_failure_events (
                    event_id                SERIAL PRIMARY KEY,
                    asset_id                TEXT,
                    event_date              DATE,
                    component                TEXT,
                    source_systems_present   TEXT[],
                    source_event_ids         TEXT[],
                    data_quality_flag        TEXT
                )
                """
            )
        )

    fact_sql = fact.copy()
    fact_sql["source_systems_present"] = fact_sql["source_systems_present"].apply(list)
    fact_sql["source_event_ids"] = fact_sql["source_event_ids"].apply(list)
    fact_sql.to_sql(
        "fact_failure_events",
        engine,
        if_exists="append",
        index=False,
        method="multi",
        chunksize=1000,
    )
    print("fact_failure_events loaded.")

    print(fact["data_quality_flag"].value_counts())


if __name__ == "__main__":
    main()
