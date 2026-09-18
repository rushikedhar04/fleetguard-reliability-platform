-- Raw layer: loaded as-is from source systems, no cleaning applied.
-- Every column is TEXT unless it's fundamentally numeric/structured in the
-- source, because "as-is" ingestion should not presuppose that messy fields
-- (dates, ids) are already well-formed.

DROP TABLE IF EXISTS raw_asset_registry;
CREATE TABLE raw_asset_registry (
    asset_id        TEXT,
    model           TEXT,
    vin_or_unit_no  TEXT,
    device_id       TEXT,
    asset_serial    TEXT
);

DROP TABLE IF EXISTS raw_service_tickets;
CREATE TABLE raw_service_tickets (
    ticket_id           TEXT,
    vin_or_unit_no      TEXT,
    reported_date       TEXT,
    technician_notes    TEXT,
    component_flagged   TEXT,
    resolution_code     TEXT
);

DROP TABLE IF EXISTS raw_telemetry;
CREATE TABLE raw_telemetry (
    device_id                  TEXT,
    timestamp                  TEXT,
    temperature_c              TEXT,
    vibration_index            TEXT,
    error_code                 TEXT,
    runtime_hours_cumulative   TEXT
);

DROP TABLE IF EXISTS raw_warranty_claims;
CREATE TABLE raw_warranty_claims (
    claim_id            TEXT,
    asset_serial        TEXT,
    claim_date          TEXT,
    component_claimed   TEXT,
    claim_amount        TEXT,
    claim_status         TEXT
);
