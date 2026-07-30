"""Typed application configuration, loaded once from the environment.

Everything the pipeline needs to know that varies between machines or between
runs lives here. Reading it through a validated Settings object — rather than
scattering os.getenv() calls across the codebase — means a missing or misspelled
variable fails loudly at startup with a clear message, instead of surfacing as a
None three functions deep.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Read from .env, and ignore variables meant for other tools (the same
    # .env also holds Grafana/Postgres vars that this app has no use for).
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Where the database is. Host is `localhost` because this code runs on your
    # machine and crosses the published port; code inside a container would use
    # `postgres`. Required — no default, so a missing .env fails immediately.
    database_url: str

    # Which extractor to use. "mock" needs no network and no secrets, so the
    # whole pipeline runs end-to-end on a fresh clone. "api" uses a live
    # provider and requires commodity_api_key.
    price_source: str = "mock"
    commodity_api_key: str = ""

    # What to pull, and how much history to request on each run.
    commodities: list[str] = ["BRENT", "WTI"]
    backfill_days: int = 7

    # The chaos switch — wired up in Sprint 4, declared now so the contract
    # is visible.
    simulate_failure: bool = False
    failure_probability: float = 0.3

    # Optional alerting — Sprint 6.
    discord_webhook_url: str = ""


@lru_cache
def get_settings() -> Settings:
    """Return the singleton Settings, built on first call.

    lru_cache makes this a lazy singleton: the .env file is parsed once, not on
    every import, and every caller shares the one object.
    """
    return Settings()
