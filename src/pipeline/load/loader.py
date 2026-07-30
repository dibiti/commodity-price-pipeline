"""Write clean prices into core.commodity_prices, idempotently.

The load is an UPSERT: insert new rows, and where a row for the same
(commodity, date, currency) already exists, update it in place. This is what
makes the pipeline safe to re-run — a retry after a timeout, or a deliberate
rerun to correct bad data, converges to the right state instead of either
duplicating rows or crashing on the unique constraint.
"""

from uuid import UUID

import pandas as pd
from sqlalchemy import Engine, text

# EXCLUDED is the row Postgres WOULD have inserted. On a conflict we take its
# price and source and refresh ingested_at, but never touch the natural key.
_UPSERT = text("""
    INSERT INTO core.commodity_prices
        (commodity_code, price_date, price, currency, source, run_id)
    VALUES
        (:commodity_code, :price_date, :price, :currency, :source, :run_id)
    ON CONFLICT (commodity_code, price_date, currency) DO UPDATE SET
        price       = EXCLUDED.price,
        source      = EXCLUDED.source,
        run_id      = EXCLUDED.run_id,
        ingested_at = now()
""")


def upsert_prices(engine: Engine, df: pd.DataFrame, run_id: UUID) -> int:
    """Upsert every row of df, tagging each with the producing run_id.

    Returns the number of records processed.
    """
    if df.empty:
        return 0

    records = df.to_dict("records")
    for record in records:
        record["run_id"] = run_id

    # engine.begin() opens a transaction that commits on success and rolls back
    # on any exception — so a failure halfway through loads nothing, rather than
    # leaving the table half-written. Passing the list of dicts runs it as a
    # single executemany round-trip, not one INSERT per row.
    with engine.begin() as conn:
        conn.execute(_UPSERT, records)

    return len(records)
