# Custom Airflow image for the commodity pipeline.
#
# It contains two independent Python environments on purpose:
#
#   1. Airflow's own environment (the base image), which pins SQLAlchemy 1.4.
#   2. An ISOLATED virtualenv at /opt/pipeline/venv holding the pipeline's own
#      dependencies (SQLAlchemy 2.0 + psycopg 3, pandas, ...).
#
# Keeping them apart is the whole trick: Airflow never imports the pipeline, it
# only LAUNCHES it as a command through the isolated venv, so the two dependency
# sets can never collide. Airflow orchestrates; the pipeline runs beside it.

FROM apache/airflow:2.10.3-python3.12

# Create a directory the unprivileged airflow user can own, for the venv.
USER root
RUN mkdir -p /opt/pipeline && chown airflow: /opt/pipeline
USER airflow

# Build the pipeline's isolated environment from the same requirements.txt the
# rest of the project uses — one source of truth for the pipeline's deps.
COPY --chown=airflow:0 requirements.txt /opt/pipeline/requirements.txt
RUN python -m venv /opt/pipeline/venv \
    && /opt/pipeline/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/pipeline/venv/bin/pip install --no-cache-dir -r /opt/pipeline/requirements.txt
