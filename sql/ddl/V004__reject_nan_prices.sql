-- ---------------------------------------------------------------------------
-- V004 — close the NaN hole at the database level too.
--
-- Sprint 4's chaos injection revealed that a missing price became a NaN which
-- passed our ck_cp_price_positive check — because PostgreSQL, uniquely, sorts
-- NaN as GREATER THAN every real number, so `'NaN'::numeric > 0` is true.
--
-- The transform now rejects NaN before it ever reaches here, but the database
-- is meant to be the LAST line of defence: it must refuse bad data regardless
-- of which code path (or careless manual INSERT) produced it. So we harden the
-- constraint itself.
--
-- The idiom `price <> 'NaN'::numeric` works because Postgres treats NaN as
-- equal to itself, so a NaN price makes `price <> 'NaN'` false and the row is
-- rejected. (The usual `price = price` trick does NOT work in Postgres, where
-- NaN = NaN is true.)
-- ---------------------------------------------------------------------------

ALTER TABLE core.commodity_prices
    DROP CONSTRAINT IF EXISTS ck_cp_price_positive;

ALTER TABLE core.commodity_prices
    ADD CONSTRAINT ck_cp_price_positive
    CHECK (price > 0 AND price <> 'NaN'::numeric);
