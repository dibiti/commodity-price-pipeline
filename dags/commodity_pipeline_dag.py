"""Airflow DAG: run the commodity ingestion pipeline once a day.

The DAG is deliberately thin. All the real work lives in src/pipeline; Airflow's
job here is only orchestration — WHEN to run, how many times to RETRY, and where
to see the RESULT. It launches the pipeline as an isolated command (see the
BashOperator below), so Airflow's dependencies never mix with the pipeline's.

This is the file the scheduler parses from /opt/airflow/dags on a timer, so it
is kept import-light: no pandas, no database, nothing heavy at module load.
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

default_args = {
    # Retries are an orchestration concern, so they live here rather than in the
    # pipeline code. A transient blip (the API times out, the DB is briefly
    # unreachable) gets two more attempts, a minute apart, before the run is
    # declared failed. A real bug will still fail all three and surface.
    "retries": 2,
    "retry_delay": timedelta(minutes=1),
}

with DAG(
    dag_id="commodity_daily",
    description="Daily commodity price ingestion",
    # Cron: 06:00 every day. Airflow runs the job for a given day shortly after
    # that day ends, on this cadence.
    schedule="0 6 * * *",
    # A fixed past date. Combined with catchup=False, the DAG will not try to
    # backfill every day since this date the first time it is unpaused — it just
    # starts running from now on. Turn catchup on only when you truly want to
    # replay history (our upsert makes that safe, but it is rarely what you want
    # by default).
    start_date=datetime(2026, 1, 1),
    catchup=False,
    default_args=default_args,
    tags=["commodity", "etl"],
) as dag:
    ingest_prices = BashOperator(
        task_id="ingest_prices",
        # Launch the pipeline through its OWN isolated virtualenv, from a working
        # directory where `src` is importable. DATABASE_URL (pointing at the app
        # database over the Docker network) is supplied by the container's
        # environment, so nothing sensitive lives in this file.
        bash_command="cd /opt/pipeline && /opt/pipeline/venv/bin/python -m src.pipeline.run_pipeline",
    )
