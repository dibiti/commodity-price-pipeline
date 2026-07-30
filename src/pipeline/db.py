"""Database engine factory.

One SQLAlchemy Engine per process, shared by every component. The Engine owns a
connection pool, so we are not opening a fresh TCP connection to Postgres on
every insert — connections are borrowed and returned.
"""

from functools import lru_cache

from sqlalchemy import Engine, create_engine

from .config import get_settings


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    # pool_pre_ping sends a lightweight check before handing out a pooled
    # connection, so one that Postgres has since dropped (a restart, an idle
    # timeout) is quietly replaced instead of blowing up mid-run.
    return create_engine(settings.database_url, pool_pre_ping=True, future=True)
