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
