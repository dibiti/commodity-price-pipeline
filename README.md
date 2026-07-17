# Commodity Price Ingestion Pipeline

A daily pipeline that pulls commodity prices into Postgres, records every run in
an audit table, and shows the results in Grafana.

It also has a switch that makes it fail on purpose — injecting schema changes,
null values or network timeouts — so the monitoring can be tested against real
failures instead of imaginary ones.

**Status:** early. Only the local infrastructure exists so far — Postgres and
Grafana in Docker. No pipeline code yet.

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
