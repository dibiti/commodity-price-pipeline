"""The orchestrator: wires extract -> transform -> load together and wraps the
whole run in an audit log.

This is the file Airflow will call in Sprint 7, and the one you run by hand
today from the project root:

    python -m src.pipeline.run_pipeline
"""

import logging
import random
from datetime import UTC, date, datetime, timedelta

from .alerting.alerter import Alert, DiscordAlerter
from .chaos.engine import ChaosEngine
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
    # No webhook set => the alerter logs instead of posting. The pipeline runs
    # the same with or without a real Discord URL.
    alerter = DiscordAlerter(settings.discord_webhook_url)

    # Decide this run's chaos outcome once, up front. On a normal run
    # (SIMULATE_FAILURE=False) the engine is inert and every hook is a no-op.
    chaos = ChaosEngine(random.Random())
    chaos.plan(
        simulate_failure=settings.simulate_failure,
        probability=settings.failure_probability,
        forced_fault=settings.chaos_fault,
    )
    if chaos.active:
        log.warning("CHAOS ARMED: injecting %s this run", chaos.fault)

    end = date.today()
    start = end - timedelta(days=settings.backfill_days - 1)

    run = RunLogger(engine, "commodity_daily")
    try:
        # Everything inside this block is one audited run. If any step raises —
        # a real fault or an injected one — the RunLogger records FAILED with
        # the full traceback and re-raises. Nothing is silently lost.
        with run:
            # Flag a simulated failure so it can be excluded from real metrics.
            run.simulated_failure = chaos.active
            run.injected_fault = chaos.fault

            log.info(
                "Run %s: fetching %s for %s..%s",
                run.run_id,
                settings.commodities,
                start,
                end,
            )

            chaos.before_extract()  # may raise an injected network timeout
            raw = source.fetch(settings.commodities, start, end)  # extract
            raw = chaos.corrupt(raw)  # may inject a schema mismatch or null
            df = normalize(raw)  # transform (where corrupted data fails)
            count = upsert_prices(engine, df, run.run_id)  # load

            run.records_processed = count
            log.info("Run %s: loaded %d rows", run.run_id, count)
    except Exception as exc:
        # Persist first, notify second: the FAILED row (with traceback) is
        # already written by RunLogger.__exit__ above. Only now do we send the
        # best-effort alert — send() never raises — and then re-raise so the
        # failure still surfaces to whoever ran the pipeline.
        alerter.send(
            Alert(
                severity="CRITICAL",
                pipeline_name="commodity_daily",
                error_type=type(exc).__name__,
                error_message=str(exc),
                timestamp=datetime.now(UTC).isoformat(),
                latency_ms=run.latency_ms,
                run_id=str(run.run_id),
                simulated=run.simulated_failure,
            )
        )
        raise


if __name__ == "__main__":
    main()
