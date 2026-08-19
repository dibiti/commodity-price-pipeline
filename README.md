# Commodity Price Ingestion Pipeline

![CI](https://github.com/dibiti/commodity-price-pipeline/actions/workflows/ci.yml/badge.svg)

A daily pipeline that pulls commodity prices into Postgres, records every run in
an audit table, and shows the results in Grafana.

It also has a switch that makes it fail on purpose — injecting schema changes,
null values or network timeouts — so the monitoring can be tested against real
failures instead of imaginary ones.

**What it does, end to end:** an Airflow DAG runs the pipeline daily; each run
extracts prices (an offline mock by default, a live API optionally), cleans and
validates them, and upserts them into Postgres. Every run — success or failure —
is recorded in an audit table that drives a Grafana dashboard and a Discord
alert. A chaos switch injects controlled failures to prove the monitoring works.

## Requirements

- Docker Desktop
- Python 3.12

## Getting started

Copy the environment template and set your own passwords in `.env`:

```powershell
Copy-Item .env.example .env
```

Start the database and Grafana:

```powershell
docker compose up -d
docker compose ps
```

Create the Python environment and install the dependencies:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt -r requirements-dev.txt
```

Run the pipeline:

```powershell
python -m src.pipeline.run_pipeline
```

By default it uses an offline mock source, so it needs no API key and no
network — the whole project runs on a fresh clone with zero secrets. Run it
twice: the second run loads the same rows without duplicating them, because the
load is an idempotent upsert on `(commodity, date, currency)`.

To use live data instead, get a free key from
[Alpha Vantage](https://www.alphavantage.co/support/#api-key) and set
`PRICE_SOURCE=api` and `COMMODITY_API_KEY=...` in `.env`.

## The chaos switch

The pipeline can break itself on purpose, to prove the monitoring works. Set
`SIMULATE_FAILURE=True` and each run has a `FAILURE_PROBABILITY` chance of one
of three faults being injected at random:

| Fault | What it imitates | Where it surfaces |
| --- | --- | --- |
| `NETWORK_TIMEOUT` | the upstream API stalling | the extract step |
| `SCHEMA_MISMATCH` | a field arriving with the wrong type | the transform step |
| `NULL_VALUES` | a required price going missing | the transform step |

Every run — clean or injected — writes one row to `ops.etl_execution_logs`
recording its status, latency, row count, error message and full traceback.
Injected failures are flagged `simulated_failure = TRUE` so they can be kept out
of real reliability metrics. Force a specific fault for a demo:

```powershell
$env:SIMULATE_FAILURE="True"; $env:CHAOS_FAULT="NULL_VALUES"
python -m src.pipeline.run_pipeline
Remove-Item Env:SIMULATE_FAILURE, Env:CHAOS_FAULT
```

Building this switch surfaced a real bug: a missing price became a `NaN` that
slipped past both the transform and the `price > 0` constraint (PostgreSQL sorts
`NaN` as greater than every number). Both layers now reject it — which is the
whole point of injecting failures on purpose.

## Dashboards

Grafana is at <http://localhost:3000> (log in with the `GRAFANA_ADMIN_*` values
from `.env`). Open **Dashboards → Pipeline → ETL Observability**.

The dashboard reads `ops.etl_execution_logs` directly and shows, at a glance:

- **Time since last success** — the freshness / dead-man's-switch metric. It
  measures the age of the last successful run, so it keeps climbing (and turns
  red) when the pipeline stops running entirely. This is the one signal that
  catches a run which never happened, because a count of existing rows can't
- **Real success rate** and **real failures**, which exclude chaos-injected
  failures (`simulated_failure = TRUE`) so a demo never dents the true numbers
- **Run latency over time**, to catch a pipeline that is slowing down
- **Injected faults breakdown**, and a **flight-recorder table** of recent runs
  with their status, latency, row count and error

The dashboard is provisioned as code from
`docker/grafana/provisioning/dashboards/`, so it appears automatically on any
clone — there is no manual setup. It fills with more history as you run the
pipeline over time.

## Alerting

A dashboard shows a failure; it does not tell you about it. When a run fails,
the pipeline sends a Discord alert with the severity, pipeline name, error type,
latency and run id.

Alerting is **optional and best-effort**, by design:

- With no `DISCORD_WEBHOOK_URL` set, the alert is logged instead of sent, so the
  pipeline (and its tests) run with no secrets at all.
- The alert is only ever attempted *after* the run's outcome is written to
  `ops.etl_execution_logs`. A slow or failing webhook loses a notification,
  never a record — the database is the source of truth.
- Delivery never raises and always times out, so a webhook problem cannot break
  the pipeline or hide the original error.

To enable it, create a webhook in a Discord server (Server Settings →
Integrations → Webhooks) and set `DISCORD_WEBHOOK_URL` in `.env`. A dedicated
server used only for this project keeps the blast radius to nothing.

## Orchestration (Airflow)

Running the pipeline by hand is fine for development; in production something has
to run it on a schedule, retry transient failures, and show the result. That is
Airflow's job. It runs as an **opt-in overlay** on top of the core stack, so
everyday work stays light:

```powershell
docker compose -f docker-compose.yml -f docker-compose.airflow.yml up -d
```

Then open the Airflow UI at <http://localhost:8080> (log in `admin` / `admin`),
enable the `commodity_daily` DAG, and trigger it. It runs daily at 06:00, with
two retries on failure.

Two design points worth knowing:

- **Airflow cannot run natively on Windows** (it needs POSIX), which is the main
  reason the whole project is containerised.
- Airflow pins older versions of some libraries the pipeline also uses, so the
  DAG never imports the pipeline. It **launches it as a command** inside an
  isolated virtualenv (see `docker/airflow/Dockerfile`), keeping the two
  dependency sets completely apart. Airflow orchestrates; the pipeline runs
  beside it and writes to the same database, which the Grafana dashboard reads.

Postgres listens on `localhost:5432`.

To confirm the database came up correctly:

```powershell
docker compose exec postgres psql -U pipeline -d commodities -c '\dn'
```

That should list three schemas: `raw` (data as received), `core` (cleaned data),
and `ops` (the pipeline's own run logs).

## Tests and CI

Run the checks locally the same way CI does:

```powershell
ruff check src tests dags        # lint
ruff format --check src tests dags
pytest -q                        # unit tests (no database needed)
```

Every push and pull request runs [GitHub Actions](.github/workflows/ci.yml):
a **quality** job (lint, format, unit tests) and an **integration** job that
starts a real Postgres, applies the schema, runs the pipeline, and asserts the
data landed. Both run with no secrets.

Optionally, install the local pre-commit hooks so lint, formatting and a
private-key check run automatically on every commit:

```powershell
pre-commit install
```

## Database schema

Two tables, in separate schemas.

`core.commodity_prices` holds the prices themselves — one row per commodity,
per day, per currency. `ops.etl_execution_logs` holds one row per pipeline run,
recording status, duration, row count and any error. Every price row carries the
`run_id` of the run that wrote it, so you can always ask which run produced a
given number, or what a failed run managed to write before it died.

Prices are stored as `NUMERIC`, not `FLOAT`. Floats cannot represent most
decimal fractions exactly, so the error compounds when you aggregate:

```sql
SELECT sum(0.10::numeric), sum(0.10::double precision)
FROM generate_series(1, 10000);
--  1000.00  |  1000.0000000001588
```

The schema lives in `sql/ddl/` as numbered migration files, applied in order:

```powershell
Get-Content sql\ddl\V001__create_etl_execution_logs.sql -Raw |
    docker compose exec -T postgres psql -U pipeline -d commodities -v ON_ERROR_STOP=1
```

They are deliberately **not** in `docker/postgres/initdb/`, which only runs on a
completely empty database. Migrations can be applied to a database that already
has data in it, which is the situation you are always in outside your laptop.

## Common commands

```powershell
docker compose up -d              # start in the background
docker compose ps                 # status and health
docker compose logs -f grafana    # follow a service's logs
docker compose down               # remove containers, keep the data
docker compose down -v            # remove containers AND delete the data
```

## Things that catch you out

The SQL in `docker/postgres/initdb/` runs **only on the first start**, while the
database volume is still empty. Editing it later, or changing the Postgres
credentials in `.env`, has no effect on a database that already exists. To apply
either, you have to wipe and rebuild:

```powershell
docker compose down -v
docker compose up -d
```

Grafana connects to Postgres at `postgres:5432` — the service name, not
`localhost`. Containers reach each other by service name over the Docker
network. `localhost:5432` is the address for tools running on Windows, and the
two are independent.
