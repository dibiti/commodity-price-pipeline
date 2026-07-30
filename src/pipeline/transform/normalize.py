"""Turn raw source records into clean rows the database will accept.

A source's output is loosely typed and provider-shaped. This step gives it the
exact column names, types and basic sanity our schema expects. We use pandas
because it is the natural tool for tabular cleaning — and, not by accident, it
is the piece that would have to change if the dataset ever grew to tens of
millions of rows (see the memory note below).
"""

from decimal import Decimal

import pandas as pd

_OUTPUT_COLUMNS = ["commodity_code", "price_date", "price", "currency", "source"]


def normalize(raw: list[dict]) -> pd.DataFrame:
    if not raw:
        # An empty extract is not an error — it is a fact the audit log will
        # record as a run that processed zero rows. Return the right shape so
        # downstream code does not special-case emptiness.
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)

    # NOTE (memory): from_records materialises the ENTIRE dataset in RAM at
    # once. Fine for hundreds or thousands of rows; the line to rethink if the
    # data ever reaches millions.
    df = pd.DataFrame.from_records(raw)

    df = df.rename(columns={"symbol": "commodity_code", "date": "price_date"})

    df["commodity_code"] = df["commodity_code"].str.upper().str.strip()
    df["currency"] = df["currency"].str.upper().str.strip()
    df["source"] = df["source"].astype(str).str.strip()
    df["price_date"] = pd.to_datetime(df["price_date"]).dt.date

    # Carry the price as Decimal, NOT float. We chose NUMERIC in the database
    # precisely to keep money exact; passing a float here would smuggle back in
    # the very rounding error the schema was designed to avoid. Decimal(str(x))
    # converts through the decimal string, so 82.13 stays exactly 82.13.
    df["price"] = df["price"].apply(lambda value: Decimal(str(value)))

    return df[_OUTPUT_COLUMNS]
