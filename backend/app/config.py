from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Railway injects this automatically when a Postgres service is attached.
    # Locally it comes from .env or the shell (see README).
    database_url: str = "postgresql://prism:prism@localhost:5435/prism"

    eodhd_api_key: str = ""
    # Ask Claude degrades to an explanatory empty state when unset.
    anthropic_api_key: str = ""
    # The ALL-IN-ONE plan allows 100k/day, so this is no longer a hard
    # constraint — it stays as a safety rail against a runaway backfill loop
    # quietly burning the quota.
    eodhd_daily_call_budget: int = 100_000

    # IG, read-only. Prism never places, amends or closes an order — it only
    # observes. There is deliberately no order-entry code path to disable.
    ig_api_key: str = ""
    ig_username: str = ""
    ig_password: str = ""
    # Live by default because Roger's accounts are live; the demo host exists
    # for testing against IG's sandbox.
    ig_demo: bool = False
    # IG's limits are strict and per-application. A few polls a day plus a
    # light intraday positions check is well inside them; this caps it.
    ig_max_polls_per_day: int = 12
    # Annualised premium IG adds over the benchmark rate on spread bet
    # funding. Published as roughly 2.5-3.4% depending on product.
    ig_funding_premium_pct: float = 3.0
    # Benchmark (SONIA for GBP). Configurable because it moves and Prism does
    # not have a rates feed.
    ig_benchmark_rate_pct: float = 4.0

    @property
    def async_database_url(self) -> str:
        """DATABASE_URL rewritten for the asyncpg driver.

        Railway supplies "postgresql://..." (older setups "postgres://..."),
        but async SQLAlchemy needs the "postgresql+asyncpg://" prefix.
        """
        url = self.database_url
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url


settings = Settings()
