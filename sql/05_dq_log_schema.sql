DROP TABLE IF EXISTS dq_check_log;
CREATE TABLE dq_check_log (
    check_run_id    UUID,
    check_name      TEXT,
    table_name      TEXT,
    rows_checked    INTEGER,
    rows_flagged    INTEGER,
    run_at          TIMESTAMP,
    sample_flagged  JSONB
);
CREATE INDEX ON dq_check_log (run_at);
CREATE INDEX ON dq_check_log (check_name);
