# FleetGuard — Field Reliability & Data Quality Platform

Built a data integration + reliability analytics platform that ingests messy multi-source field failure data, documents full source-to-target lineage, catches data quality issues before they hit a dashboard, and surfaces failure trends stakeholders can actually act on.

**The scenario:** a product quality/reliability team needs to decide which fleet component is worth escalating for investigation or recall — and needs to trust the number, and be able to trace it back to source, before they act on it.

**The problem it simulates:** field failure data scattered across three disconnected systems that were never designed to talk to each other — a service ticket system (human-entered, messy), a telemetry pipeline (high-volume sensor data), and a warranty claims system (structured, but using its own asset ID scheme and its own component taxonomy). No reconciliation exists between them out of the box.

## Architecture

```mermaid
flowchart LR
    subgraph Sources ["Synthetic source systems"]
        ST[Service Tickets\nmessy, free-text]
        TL[Telemetry\nhigh-volume readings]
        WC[Warranty Claims\ndifferent ID + taxonomy]
        AR[Asset Registry\nmaster data]
    end

    ST --> RAW[(raw_* tables\nPostgres, unmodified)]
    TL --> RAW
    WC --> RAW
    AR --> RAW

    RAW --> XW[asset_crosswalk\nID normalization + join]
    XW --> DIM[dim_asset]
    XW --> FT[fact_telemetry_readings]
    XW --> FF[fact_failure_events\n7-day reconciliation]

    FF --> DQ[dq_check_log\naudit trail]
    FT --> DQ
    FF --> REL[component_reliability_stats\nMTBF + Weibull]

    DQ --> DASH[Streamlit dashboard]
    REL --> DASH
    FF --> DASH
```

## Tech stack

Python 3.11, pandas/numpy, Postgres (Docker), plain SQL views + `mappings.yml` for lineage (no dbt — kept the tooling proportional to project size), scipy for Weibull fitting, Streamlit for the dashboard.

## Repo layout

```
data/generate_data.py     synthetic source data, with documented messiness injection
sql/                       raw schema, ID-normalization functions, crosswalk/dim/fact DDL
scripts/                   pipeline: load_raw, transform (reconciliation), dq_checks, reliability, render_lineage
mappings.yml               source-to-target lineage spec (the trust artifact)
docs/lineage.md            mappings.yml rendered to markdown (auto-generated, don't edit directly)
dashboard/app.py           Streamlit app: Overview / Component Deep Dive / Data Quality / Lineage
```

## How the messiness was designed

`data/generate_data.py` doesn't just add random noise to a clean dataset — it generates data the way each source system would actually produce it, then documents each injection at the point it's introduced:

- **Three different ID schemes.** Service tickets reference assets by VIN or unit number (`VIN-XXXXXXXXXXXXXXXXX`, bare VIN, or `UNIT-1234`), telemetry uses a device ID (`DEV-000123`), warranty claims use a serial number (`SN-XXXXXXXX`). None of these are the canonical `asset_id` — that only exists in a fourth "master data" source (`asset_registry`), and even there, each raw ID is formatted inconsistently relative to how the transactional systems write it (case, dashes, prefixes). Resolving these to one `asset_id` requires real normalization logic (`sql/02_normalize_functions.sql`), not a plain join.
- **Mixed date formats** across `MM/DD/YYYY`, ISO 8601, `DD-Mon-YYYY`, and ISO-with-timestamp — parsed with `dateutil` rather than assumed.
- **~15% of service tickets** are missing `component_flagged` (a technician forgot to fill it in) — the component is buried in free-text `technician_notes` instead.
- **A deliberate taxonomy mismatch**: warranty claims use internal codes (`brake_assembly`, `fuel_system`, ...) that map to the service-ticket component names via a maintained reference table — except two codes (`misc_repair`, `unclassified`) that have no mapping at all, on purpose.
- **~1,920 orphaned warranty claims** (25% of claims) with no supporting service ticket or telemetry fault anywhere — this is "the trust problem" made visible: a claim exists, but there's no other evidence backing it up.
- **~80 duplicate service tickets** re-logging the same asset/component/date (simulating a technician re-opening or double-entering a ticket).
- **~4% of telemetry readings** are sensor glitches — physically implausible values (e.g. -999°C) or nulls — injected independently of the fault-code readings.

## Lineage: the trust artifact

`mappings.yml` documents, per target field: the source table/field, the exact transformation applied, and — for `fact_failure_events` — the business rule that defines what counts as one reconciled failure event. It's written alongside the transform code, not after the fact, and it's rendered into `docs/lineage.md` and the dashboard's **Lineage** tab so a reviewer can click through and answer "where did this number come from" without reading source code.

**The reconciliation rule**, concretely: a failure event is any service ticket, any telemetry reading carrying a non-null `error_code`, or any warranty claim, resolved to a canonical `asset_id`. Events on the *same* asset within a rolling 7-day window are merged into one event, recording which of the three systems contributed evidence (`source_systems_present`).

## Data quality — surfaced, not hidden

`scripts/dq_checks.py` runs five checks against the integrated tables and writes every result — including a JSON sample of flagged rows — to `dq_check_log`, an auditable table the dashboard reads directly (no check result is ever discarded, only reported). On the current dataset:

| Check | Flagged | Catches |
|---|---|---|
| Missing `component_flagged` | 15.5% of tickets | technician left the field blank |
| Orphaned warranty claims | 1,920 events (3.0%) | claim with no ticket/telemetry support |
| Telemetry outliers | 44,011 readings (4.0%) | out-of-range or null sensor values |
| Taxonomy mismatch | 132 claims (4.1%) | claim component code with no canonical mapping |
| Duplicate service tickets | 91 tickets (0.5%) | same asset/component logged twice within 2 days |

## Reliability statistics

MTBF and a `scipy.stats.weibull_min` fit are computed per component from reconciled inter-failure intervals (`scripts/reliability.py`), with fits only reported for components with ≥20 usable intervals — small-sample Weibull fits are flagged as ineligible rather than shown as if trustworthy.

Worked example — **Sensor Module** (2,018 reconciled events, 1,705 assets affected):
- MTBF ≈ 250 days
- Failure rate ≈ 0.135 / asset-year
- Weibull shape *k* = 1.24, scale λ ≈ 267 days → mild wear-out pattern (k slightly above 1, not early-life infant-mortality or purely random failure)

## Dashboard

Four tabs, all reading live from Postgres:
1. **Overview** — fleet-wide failure trend, top components by count
2. **Component Deep Dive** — MTBF, failure trend, Weibull survival curve per component
3. **Data Quality** — the `dq_check_log`, drill into flagged rows per check — this is the tab most portfolio dashboards skip
4. **Lineage** — `mappings.yml` rendered readably, so a stakeholder can trace any number back to source

## Running locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

docker compose up -d          # Postgres on localhost:5433

python data/generate_data.py  # writes data/raw/*.csv

python scripts/run_pipeline.py   # load raw -> crosswalk -> reconcile -> DQ checks -> reliability -> lineage docs

streamlit run dashboard/app.py
```

By default the app connects to `postgresql+psycopg2://fleetguard:fleetguard@localhost:5433/fleetguard`; override with the `DATABASE_URL` env var (e.g. for a deployed Postgres instance).

## Deployment

Deploy Postgres + the Streamlit app on Railway or Render: provision a Postgres instance, set `DATABASE_URL` on the app service, run `scripts/run_pipeline.py` once against the deployed database (or as a one-off job), then point the web service at `streamlit run dashboard/app.py --server.port $PORT --server.address 0.0.0.0`.
