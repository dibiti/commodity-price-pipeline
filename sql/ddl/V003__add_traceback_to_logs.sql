-- ---------------------------------------------------------------------------
-- V003 — add a full-traceback column to the audit log.
--
-- Sprint 4 introduces deliberate failures, and a support engineer debugging one
-- needs more than a one-line summary — they need the exact stack trace that a
-- Python exception produces. `error_message` stays as the short, human-readable
-- headline that dashboards and alerts show; `traceback` holds the full detail.
--
-- This is exactly the situation migrations exist for: the table already has
-- data and is referenced by a foreign key, so it cannot be dropped and
-- recreated from initdb/. ADD COLUMN ... (nullable, no default) is a metadata-
-- only change in Postgres — instant, and it does not rewrite existing rows.
-- ---------------------------------------------------------------------------

ALTER TABLE ops.etl_execution_logs
    ADD COLUMN IF NOT EXISTS traceback TEXT;

COMMENT ON COLUMN ops.etl_execution_logs.traceback IS
    'Full Python traceback for a FAILED run. NULL for successful runs.';
