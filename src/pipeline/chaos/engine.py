"""The Chaos Switch: controlled, deliberate failure injection.

The project's signature feature. When armed (SIMULATE_FAILURE=True), each run has
a FAILURE_PROBABILITY chance of having one of three faults injected at random:

  - NETWORK_TIMEOUT : an artificial latency followed by a timeout, as if the
                      upstream API stalled. Raised at the extract boundary.
  - SCHEMA_MISMATCH : a value of the wrong type slipped into the data, as if the
                      provider changed a field. Surfaces in the transform step.
  - NULL_VALUES     : a required price blanked out, as if the feed dropped a
                      value. Surfaces in the transform step.

Design choices worth noting:

* Chaos lives in ONE module, not scattered as `if simulate:` branches through
  the pipeline. The orchestrator calls two clearly-named hooks; everything else
  is unaware chaos exists. Same principle as the swappable PriceSource.

* Two of the three faults corrupt the DATA and then let the REAL pipeline fail
  naturally — we do not fake the error. That proves our genuine transform and
  database defences catch bad data, which is the whole point of the exercise.
  Only NETWORK_TIMEOUT, which has no data to corrupt, is raised directly.

* The decision (armed? which fault?) is made ONCE per run, in `plan()`, so a
  run's behaviour is coherent and can be recorded in the audit log.
"""

import time
from collections.abc import Sequence

# The canonical fault codes. These are the exact strings stored in
# ops.etl_execution_logs.injected_fault.
NETWORK_TIMEOUT = "NETWORK_TIMEOUT"
SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
NULL_VALUES = "NULL_VALUES"
ALL_FAULTS = (NETWORK_TIMEOUT, SCHEMA_MISMATCH, NULL_VALUES)


class ChaosNetworkTimeout(TimeoutError):
    """Raised by the chaos engine to imitate an upstream network timeout.

    Subclasses the builtin TimeoutError so that, to the rest of the system, an
    injected timeout is indistinguishable from a real one — which is exactly
    what we want to test.
    """


class ChaosEngine:
    def __init__(self, rng, *, latency_seconds: float = 0.5):
        # An injected random.Random, so tests can seed it for determinism while
        # real runs pass a system-seeded one.
        self._rng = rng
        self._latency_seconds = latency_seconds
        self.active: bool = False
        self.fault: str | None = None

    def plan(
        self, *, simulate_failure: bool, probability: float, forced_fault: str = ""
    ) -> None:
        """Decide, once, whether this run fails and how.

        forced_fault (from an optional config override) makes a specific fault
        fire deterministically — used to demo or test each fault in isolation.
        Otherwise the fault is chosen at random when the probability roll hits.
        """
        if not simulate_failure:
            self.active = False
            self.fault = None
            return

        if forced_fault:
            self.active = True
            self.fault = forced_fault
            return

        self.active = self._rng.random() < probability
        self.fault = self._rng.choice(ALL_FAULTS) if self.active else None

    def before_extract(self) -> None:
        """Hook called just before fetching data.

        If this run's fault is a network timeout, wait (to imitate a stalled
        connection, which shows up as elevated latency in the audit log) and
        then raise. A no-op for every other fault.
        """
        if self.active and self.fault == NETWORK_TIMEOUT:
            time.sleep(self._latency_seconds)
            raise ChaosNetworkTimeout(
                f"Simulated upstream timeout after {self._latency_seconds}s"
            )

    def corrupt(self, records: Sequence[dict]) -> list[dict]:
        """Hook called on the freshly-fetched records, before transform.

        For data-shaped faults, mutate the first record so the real transform
        step chokes on it. For everything else, return the records untouched.
        """
        result = [dict(r) for r in records]  # copy; never mutate the source's data
        if not self.active or not result:
            return result

        if self.fault == SCHEMA_MISMATCH:
            # A non-numeric price, as if the provider sent "N/A". The transform's
            # Decimal conversion will reject it.
            result[0]["price"] = "not-a-number"
        elif self.fault == NULL_VALUES:
            # A missing required price. Fails transform (and the NOT NULL column
            # behind it) — a required field cannot simply vanish.
            result[0]["price"] = None

        return result
