-- ---------------------------------------------------------------------------
-- Bootstrap: namespaces only.
--
-- IMPORTANT — read before adding to this directory:
-- The postgres image runs these scripts ONLY when the data directory is empty,
-- i.e. on the very first boot against a fresh `pgdata` volume. Adding a new
-- file here later will NOT apply it to a database that already exists. That
-- surprises almost everyone once.
--
-- So: this directory is for bootstrap that must exist before anything else.
-- Evolving schema (tables, columns, indexes) belongs in versioned migrations
-- under sql/ddl/, applied by the application — which is how it would work
-- against a managed RDS instance we cannot re-create at will.
-- ---------------------------------------------------------------------------

-- Separating raw landing data from modelled data is a habit worth forming
-- early: it makes "is this bad data or a bad transform?" answerable.
CREATE SCHEMA IF NOT EXISTS raw;      -- as-received payloads, minimally typed
CREATE SCHEMA IF NOT EXISTS core;     -- cleaned, typed, business-ready facts
CREATE SCHEMA IF NOT EXISTS ops;      -- pipeline's own telemetry (etl_execution_logs)

COMMENT ON SCHEMA raw  IS 'Landing zone. Ingested as received, no business rules applied.';
COMMENT ON SCHEMA core IS 'Modelled commodity price facts. Query this for analytics.';
COMMENT ON SCHEMA ops  IS 'Pipeline observability: run audit logs, data quality results.';
