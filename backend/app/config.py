"""Application settings, loaded from environment / .env via pydantic-settings.

Keeping config in one typed Settings object (instead of scattered os.getenv
calls) is the standard FastAPI pattern: import `settings` anywhere you need it.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # MongoDB
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "chronosense"
    # One collection now: radar-only vital-sign captures (respiration + heartbeat).
    capture_collection: str = "captures"

    # Used only by the ingest script to locate the per-capture vital-sign JSONs.
    dataset_root: str = "../FMCW_dataset"


settings = Settings()
