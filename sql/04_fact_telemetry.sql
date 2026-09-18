-- fact_telemetry_readings: raw telemetry resolved to canonical asset_id,
-- with implausible readings flagged (not dropped — the DQ layer surfaces
-- these, it does not silently filter them).

DROP TABLE IF EXISTS fact_telemetry_readings;
CREATE TABLE fact_telemetry_readings AS
SELECT
    cw.asset_id,
    cw.model,
    t.device_id                                        AS device_id_raw,
    (t.timestamp)::timestamp                            AS reading_ts,
    NULLIF(t.temperature_c, '')::float8                 AS temperature_c,
    NULLIF(t.vibration_index, '')::float8                AS vibration_index,
    t.error_code,
    NULLIF(t.runtime_hours_cumulative, '')::float8       AS runtime_hours_cumulative,
    CASE
        WHEN NULLIF(t.temperature_c, '')::float8 IS NULL THEN TRUE
        WHEN NULLIF(t.temperature_c, '')::float8 NOT BETWEEN -40 AND 150 THEN TRUE
        WHEN NULLIF(t.vibration_index, '')::float8 IS NULL THEN TRUE
        WHEN NULLIF(t.vibration_index, '')::float8 NOT BETWEEN 0 AND 5 THEN TRUE
        ELSE FALSE
    END AS is_outlier
FROM raw_telemetry t
JOIN asset_crosswalk cw
    ON normalize_device_id(t.device_id) = cw.device_id_key;

CREATE INDEX ON fact_telemetry_readings (asset_id);
CREATE INDEX ON fact_telemetry_readings (reading_ts);
