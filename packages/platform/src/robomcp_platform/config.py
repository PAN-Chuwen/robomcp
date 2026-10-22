"""Platform settings, read from the environment and `.env` (see `.env.example`)."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ROBOMCP_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://robomcp@localhost:5442/robomcp"

    # Object storage for episode artifacts (MinIO in dev); without an endpoint, artifacts go to artifact_dir.
    s3_endpoint_url: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_bucket: str = "robomcp"
    artifact_dir: str = "out/artifacts"

    # Job queue
    heartbeat_interval_s: float = 5.0
    heartbeat_timeout_s: float = 30.0
    max_attempts: int = 3
    poll_interval_s: float = 1.0
    max_episodes_per_experiment: int = 10_000

    # Dotted path "module:attr" to a zero-argument factory returning an EpisodeRunner.
    worker_runner: str = "robomcp_platform.runner:HarnessRunner"


@lru_cache
def get_settings() -> Settings:
    return Settings()
