-- ---------------------------------------------------------------------------
-- V002 — core.commodity_prices
--
-- The business fact table: one row per commodity, per day, per currency.
-- Depends on V001 because every price row records which run produced it.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS core.commodity_prices (

    price_id        BIGSERIAL PRIMARY KEY,

    -- A short stable code (GOLD, BRENT, WHEAT) rather than a display name.
    -- Names get renamed and re-spelled; codes are what you join on.
    commodity_code  TEXT        NOT NULL,

    -- DATE, not TIMESTAMPTZ. This is a daily closing price — the business
    -- meaning is "the price for the 14th", not "the price at 14:32:07". Using
    -- a timestamp here would invite duplicate rows that differ only by a few
    -- meaningless seconds, and would break the uniqueness rule below.
    price_date      DATE        NOT NULL,

    -- ── The single most important type decision in this file ──────────────
    -- NUMERIC, never FLOAT/REAL/DOUBLE PRECISION. Explained at length in the
    -- README, but in short: floats cannot represent most decimal fractions
    -- exactly, so sums drift. NUMERIC is exact decimal arithmetic.
    --
    -- (18, 6) = 18 significant digits, 6 after the point. Six decimals is
    -- generous for a price and leaves room for low-value commodities and for
    -- FX-converted values without rounding at storage time.
    price           NUMERIC(18, 6) NOT NULL,

    -- Replaces your `price_usd` + `currency` pair, which contradicted itself:
    -- if the column is always USD the currency is redundant, and if it is not,
    -- the name lies. A neutral `price` plus an explicit currency cannot drift
    -- out of sync. CHAR(3) matches the ISO 4217 standard (USD, EUR, GBP).
    currency        CHAR(3)     NOT NULL DEFAULT 'USD',

    -- Which API this came from. When two sources disagree — and they do — the
    -- first question is always "where did this number come from?".
    source          TEXT        NOT NULL,

    -- ── Lineage ───────────────────────────────────────────────────────────
    -- The link back to the run that produced this row. This is what makes
    -- "run 47 failed — what did it write before dying?" an answerable question
    -- instead of a forensic exercise.
    --
    -- The foreign key also enforces ordering: the audit row must exist before
    -- any data references it, so the pipeline physically cannot load data
    -- without first announcing itself. The default ON DELETE RESTRICT means
    -- nobody can delete a run's audit record while its data still exists.
    run_id          UUID        NOT NULL
                    REFERENCES ops.etl_execution_logs (run_id),

    -- When the row landed. Distinct from price_date: a price for the 14th may
    -- be ingested on the 15th after a retry, and the gap between the two is a
    -- freshness metric worth charting.
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- ── Idempotency ───────────────────────────────────────────────────────
    -- The most valuable constraint in this file. A scheduled pipeline WILL run
    -- twice on the same day — a retry after a timeout, a manual backfill,
    -- someone clicking "clear" in Airflow. Without this, each rerun silently
    -- duplicates every row and every average you compute is quietly wrong.
    --
    -- With it, the database refuses the duplicate, and in Sprint 3 we write
    -- INSERT ... ON CONFLICT (...) DO UPDATE so a rerun safely corrects the
    -- existing row instead. That is what makes a pipeline re-runnable, which
    -- is the property that lets you fix a bad day by just running it again.
    CONSTRAINT uq_commodity_prices_natural_key
        UNIQUE (commodity_code, price_date, currency),

    -- A negative or zero commodity price is not a thing we intend to store.
    -- (Real caveat: oil futures went negative in April 2020. If this project
    -- ever tracked futures rather than spot prices, this constraint would be
    -- wrong — a good reminder that constraints encode business assumptions,
    -- and assumptions need revisiting.)
    CONSTRAINT ck_cp_price_positive
        CHECK (price > 0),

    -- Catches lowercase or malformed currency codes at the door.
    CONSTRAINT ck_cp_currency_is_iso
        CHECK (currency ~ '^[A-Z]{3}$'),

    -- A price dated in the future is a parsing bug, not market data.
    CONSTRAINT ck_cp_price_date_not_future
        CHECK (price_date <= CURRENT_DATE)
);

-- The main analytical access pattern: one commodity's recent history.
-- Column order matters — commodity_code first because queries filter on it
-- with equality, then price_date for the range scan and ordering.
CREATE INDEX IF NOT EXISTS ix_cp_commodity_date
    ON core.commodity_prices (commodity_code, price_date DESC);

-- Postgres automatically indexes PRIMARY KEY and UNIQUE constraints, but it
-- does NOT index foreign keys. Without this, "which rows did run X write?"
-- means a full table scan, and so does deleting a log row (Postgres has to
-- check every price row for references). Unindexed FKs are one of the most
-- common quiet performance problems in production databases.
CREATE INDEX IF NOT EXISTS ix_cp_run_id
    ON core.commodity_prices (run_id);

COMMENT ON TABLE core.commodity_prices IS
    'Daily commodity closing prices. One row per commodity, date and currency.';
COMMENT ON COLUMN core.commodity_prices.run_id IS
    'The pipeline run that produced this row. Joins to ops.etl_execution_logs.';
