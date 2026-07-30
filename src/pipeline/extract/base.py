"""The contract every price source must satisfy.

This is the object-oriented heart of the pipeline. The orchestrator never knows
or cares whether prices came from an offline mock or a live API — it only knows
it holds a PriceSource with a .fetch() method. Swapping one for the other is a
config change, not a code change.

This is the Strategy pattern, and it is what keeps the mock/real split clean
instead of a tangle of if-statements spread through the loading code.
"""

from abc import ABC, abstractmethod
from datetime import date


class PriceSource(ABC):
    """Abstract base class: something that can produce daily commodity prices."""

    @abstractmethod
    def fetch(self, commodities: list[str], start: date, end: date) -> list[dict]:
        """Return raw price records for the given commodities and date range.

        Each record is a loosely-typed dict shaped like the source returned it,
        e.g. {"symbol": "BRENT", "date": "2026-07-30", "price": 82.13,
        "currency": "USD", "source": "mock"}. Cleaning and typing happen later,
        in the transform step — a source's only job is to go and get the data.
        """
        raise NotImplementedError
