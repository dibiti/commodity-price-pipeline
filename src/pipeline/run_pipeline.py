"""The orchestrator: wires extract -> transform -> load together and wraps the
whole run in an audit log.

This is the file Airflow will call in Sprint 7, and the one you run by hand
today from the project root:

    python -m src.pipeline.run_pipeline
"""

import logging
from datetime import date, timedelta

from .config import Settings, get_settings
from .db import get_engine
from .extract.api_source import AlphaVantagePriceSource
from .extract.base import PriceSource
from .extract.mock_source import MockPriceSource
from .load.loader import upsert_prices
from .observability.audit import RunLogger
from .transform.normalize import normalize

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
)
log = logging.getLogger("pipeline")


def make_source(settings: Settings) -> PriceSource:
    """Pick the extractor from config.

    Defaults to the offline mock, so the pipeline runs with no secrets unless
    you explicitly ask for — and have a key for — the live API.
    """
    if settings.price_source == "api" and settings.commodity_api_key:
        log.info("Using live Alpha Vantage source")
        return AlphaVantagePriceSource(settings.commodity_api_key)
    log.info("Using offline mock source")
    return MockPriceSource()


def main() -> None:
    settings = get_settings()
    engine = get_engine()
    source = make_source(settings)

    end = date.today()
    start = end - timedelta(days=settings.backfill_days - 1)

    # Everything inside this block is one audited run. If any step raises, the
    # RunLogger records FAILED (with the error) and re-raises — nothing is
    # silently lost.
    with RunLogger(engine, "commodity_daily") as run:
        log.info(
            "Run %s: fetching %s for %s..%s",
            run.run_id,
            settings.commodities,
            start,
            end,
        )

        raw = source.fetch(settings.commodities, start, end)  # extract
        df = normalize(raw)  # transform
        count = upsert_prices(engine, df, run.run_id)  # load

        run.records_processed = count
        log.info("Run %s: loaded %d rows", run.run_id, count)


if __name__ == "__main__":
    main()
