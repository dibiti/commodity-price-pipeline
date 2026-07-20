# Commodity Price Ingestion Pipeline

A daily pipeline that pulls commodity prices into Postgres, records every run in
an audit table, and shows the results in Grafana.

It also has a switch that makes it fail on purpose — injecting schema changes,
null values or network timeouts — so the monitoring can be tested against real
failures instead of imaginary ones.

**Status:** early. The infrastructure and the database schema exist. There is no
pipeline code yet — nothing is fetching prices so far.

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

Grafana is at <http://localhost:3000>, using the login you set in `.env`.
Postgres listens on `localhost:5432`.

To confirm the database came up correctly:

```powershell
docker compose exec postgres psql -U pipeline -d commodities -c '\dn'
```

That should list three schemas: `raw` (data as received), `core` (cleaned data),
and `ops` (the pipeline's own run logs).

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
