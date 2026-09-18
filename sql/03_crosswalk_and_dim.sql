-- asset_crosswalk: the canonical ID resolution table. Built once from
-- raw_asset_registry (the master-data source), storing both the raw form
-- of each identifier (for display/lineage) and its normalized join key
-- (for matching against the transactional sources).

DROP TABLE IF EXISTS asset_crosswalk;
CREATE TABLE asset_crosswalk AS
SELECT
    asset_id,
    model,
    vin_or_unit_no                              AS vin_or_unit_no_raw,
    normalize_vin_or_unit(vin_or_unit_no)       AS vin_or_unit_no_key,
    device_id                                   AS device_id_raw,
    normalize_device_id(device_id)              AS device_id_key,
    asset_serial                                AS asset_serial_raw,
    normalize_asset_serial(asset_serial)        AS asset_serial_key
FROM raw_asset_registry;

CREATE UNIQUE INDEX ON asset_crosswalk (asset_id);
CREATE INDEX ON asset_crosswalk (vin_or_unit_no_key);
CREATE INDEX ON asset_crosswalk (device_id_key);
CREATE INDEX ON asset_crosswalk (asset_serial_key);

-- component_taxonomy_map: reference table maintained by the integration
-- team, mapping the warranty-claims component taxonomy back to the
-- service-ticket taxonomy. Codes with no mapping stay unmapped on purpose —
-- the DQ layer is responsible for surfacing those, not this table.
DROP TABLE IF EXISTS component_taxonomy_map;
CREATE TABLE component_taxonomy_map (
    claim_component_code   TEXT PRIMARY KEY,
    canonical_component    TEXT
);
INSERT INTO component_taxonomy_map (claim_component_code, canonical_component) VALUES
    ('brake_assembly',       'Brake Pad'),
    ('fuel_system',          'Fuel Injector'),
    ('cooling_unit',         'Cooling Fan'),
    ('battery_module',       'Battery Pack'),
    ('sensor_pkg',           'Sensor Module'),
    ('drivetrain',           'Transmission'),
    ('electrical_charging',  'Alternator'),
    ('hvac_compressor',      'Compressor'),
    ('hydraulics',           'Hydraulic Pump'),
    ('emissions_valve',      'Exhaust Valve');
    -- 'misc_repair' and 'unclassified' intentionally have no row here.

-- dim_asset: canonical asset dimension.
DROP TABLE IF EXISTS dim_asset;
CREATE TABLE dim_asset AS
SELECT asset_id, model
FROM asset_crosswalk;

CREATE UNIQUE INDEX ON dim_asset (asset_id);
