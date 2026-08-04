"""Turn raw source records into clean rows the database will accept.

A source's output is loosely typed and provider-shaped. This step gives it the
exact column names, types and basic sanity our schema expects. We use pandas
because it is the natural tool for tabular cleaning — and, not by accident, it
is the piece that would have to change if the dataset ever grew to tens of
millions of rows (see the memory note below).
"""

from decimal import Decimal, InvalidOperation

import pandas as pd

_OUTPUT_COLUMNS = ["commodity_code", "price_date", "price", "currency", "source"]
_REQUIRED = ["commodity_code", "price_date", "price", "currency"]


class DataQualityError(ValueError):
    """Raised when incoming data violates a rule the pipeline must not pass on.

    A distinct type so callers (and the audit log) can tell a data-quality
    rejection apart from an ordinary bug.
    """


def _to_decimal(value) -> Decimal:
    """Convert one price to an exact Decimal, refusing anything that is not a
    finite number.

    This is where the Sprint 4 chaos taught us a lesson. A missing price
    arrives from pandas as NaN, and BOTH Decimal("nan") and Postgres accept it
    (Postgres even reports NaN > 0 as true), so a blank price slipped silently
    into the table. We reject non-numeric and non-finite values explicitly.
    """
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise DataQualityError(f"price is not numeric: {value!r}") from None
    if not result.is_finite():  # catches NaN and +/-Infinity
        raise DataQualityError(f"price is not a finite number: {value!r}")
    return result


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

    # Reject missing required fields up front. isna() catches both Python None
    # and pandas NaN, so a dropped field fails here with a clear message rather
    # than sneaking through as NaN. This is the fix for the null-injection hole.
    missing = [col for col in _REQUIRED if df[col].isna().any()]
    if missing:
        raise DataQualityError(f"required field(s) contain null/NaN: {missing}")

    # Carry the price as Decimal, NOT float. We chose NUMERIC in the database
    # precisely to keep money exact; passing a float here would smuggle back in
    # the very rounding error the schema was designed to avoid. _to_decimal also
    # rejects non-numeric and non-finite values.
    df["price"] = df["price"].apply(_to_decimal)

    return df[_OUTPUT_COLUMNS]
