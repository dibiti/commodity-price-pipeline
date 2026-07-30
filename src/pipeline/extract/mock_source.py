"""A deterministic, offline price source.

Generates plausible daily prices with a small random walk, seeded so the same
date range always produces the same numbers. Needs no network, no API key and
has no rate limits — which is why it is the default. The whole project can be
cloned and run to completion with zero secrets, and the tests get a stable,
repeatable input.
"""

from datetime import date, timedelta
import random

from .base import PriceSource

# Rough starting points in USD, so the generated series look like real oil.
_SEED_PRICES = {"BRENT": 82.0, "WTI": 78.0}


class MockPriceSource(PriceSource):
    def fetch(self, commodities: list[str], start: date, end: date) -> list[dict]:
        records: list[dict] = []
        for symbol in commodities:
            price = _SEED_PRICES.get(symbol, 50.0)
            # Seed per symbol + range so each series is stable across runs
            # (important: it means re-running is a true no-op via the upsert).
            rng = random.Random(f"{symbol}-{start}-{end}")
            day = start
            while day <= end:
                # A small daily random walk: nudge the previous price a little.
                price = round(price * (1 + rng.uniform(-0.02, 0.02)), 4)
                records.append(
                    {
                        "symbol": symbol,
                        "date": day.isoformat(),
                        "price": price,
                        "currency": "USD",
                        "source": "mock",
                    }
                )
                day += timedelta(days=1)
        return records
