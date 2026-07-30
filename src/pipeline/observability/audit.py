"""The run logger: writes exactly one audit row per pipeline run.

Used as a context manager, so the log is guaranteed to be closed out no matter
how the run ends:

    with RunLogger(engine, "commodity_daily") as run:
        ...do the work...
        run.records_processed = n

On entry it writes a RUNNING row and commits it immediately — so the run_id
exists for the price rows' foreign key, and Grafana can see the run in flight.
On a clean exit it updates the row to SUCCESS; on an exception it updates to
FAILED with the error message and lets the exception propagate. If the process
is killed so abruptly that __exit__ never runs, the row simply stays RUNNING —
which is itself the signal that a run started and never finished.
"""

import time
from uuid import UUID, uuid4

from sqlalchemy import Engine, text

_INSERT_RUNNING = text("""
    INSERT INTO ops.etl_execution_logs (run_id, pipeline_name, status)
    VALUES (:run_id, :pipeline_name, 'RUNNING')
""")

_FINISH = text("""
    UPDATE ops.etl_execution_logs
       SET status            = :status,
           finished_at       = now(),
           latency_ms        = :latency_ms,
           records_processed = :records_processed,
           error_message     = :error_message
     WHERE run_id = :run_id
""")


class RunLogger:
    def __init__(self, engine: Engine, pipeline_name: str):
        self._engine = engine
        self._pipeline_name = pipeline_name
        # The run_id is minted in Python, before anything is written, so the
        # loader can stamp it onto every price row of this run.
        self.run_id: UUID = uuid4()
        self.records_processed: int | None = None
        self._start = 0.0

    def __enter__(self) -> "RunLogger":
        # monotonic(), not wall-clock time: it never runs backwards, so the
        # latency measurement stays correct even across a clock adjustment.
        self._start = time.monotonic()
        with self._engine.begin() as conn:
            conn.execute(
                _INSERT_RUNNING,
                {"run_id": self.run_id, "pipeline_name": self._pipeline_name},
            )
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        latency_ms = int((time.monotonic() - self._start) * 1000)
        if exc_type is None:
            status, error_message = "SUCCESS", None
        else:
            # str(exc) satisfies the ck_eel_failure_has_message constraint:
            # a FAILED row must always carry an explanation.
            status, error_message = "FAILED", f"{exc_type.__name__}: {exc}"

        with self._engine.begin() as conn:
            conn.execute(
                _FINISH,
                {
                    "run_id": self.run_id,
                    "status": status,
                    "latency_ms": latency_ms,
                    "records_processed": self.records_processed,
                    "error_message": error_message,
                },
            )

        # Return False so we never swallow the exception — the audit row is
        # written, and the error still propagates to whoever ran the pipeline.
        return False
