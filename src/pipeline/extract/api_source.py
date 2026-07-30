"""A live price source: Alpha Vantage's free commodity endpoints.

Used only when PRICE_SOURCE=api and COMMODITY_API_KEY is set. It is the
non-default path on purpose: it needs a key and is subject to rate limits, so it
must never be required just to run or test the pipeline.

Not exercised in this sprint because it needs a live key — get a free one at
https://www.alphavantage.co/support/#api-key and set it in .env to enable it.
"""

from datetime import date

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .base import PriceSource

# Alpha Vantage exposes one "function" name per commodity.
_FUNCTIONS = {"BRENT": "BRENT", "WTI": "WTI"}
_BASE_URL = "https://www.alphavantage.co/query"


class AlphaVantagePriceSource(PriceSource):
    def __init__(self, api_key: str):
        self._api_key = api_key

    # Retry ONLY on transient network faults, backing off 1s, 2s, 4s, up to
    # three attempts. A bug in our own code does not raise RequestException, so
    # it is never retried — only real transient faults get a second chance.
    # This is exactly the machinery the Sprint 4 network-timeout injection will
    # exercise: we want retries to paper over blips, not to hide real failures.
    @retry(
        retry=retry_if_exception_type(requests.RequestException),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    def _get(self, function: str) -> dict:
        response = requests.get(
            _BASE_URL,
            params={"function": function, "interval": "daily", "apikey": self._api_key},
            timeout=10,  # never hang forever on a stalled connection
        )
        response.raise_for_status()
        return response.json()

    def fetch(self, commodities: list[str], start: date, end: date) -> list[dict]:
        records: list[dict] = []
        for symbol in commodities:
            function = _FUNCTIONS.get(symbol)
            if function is None:
                continue  # this provider does not know the symbol; skip it
            payload = self._get(function)
            for point in payload.get("data", []):
                # Alpha Vantage marks missing observations with ".".
                if point.get("value") in (None, ".", ""):
                    continue
                point_date = date.fromisoformat(point["date"])
                if start <= point_date <= end:
                    records.append(
                        {
                            "symbol": symbol,
                            "date": point["date"],
                            "price": float(point["value"]),
                            "currency": "USD",
                            "source": "alphavantage",
                        }
                    )
        return records
