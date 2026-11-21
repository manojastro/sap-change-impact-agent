"""Application settings (pydantic-settings).

Every value can be overridden via environment variables or a .env file at the
project root. Defaults describe a fully self-contained simulation.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str = "SAP Change Impact & Regression Risk Agent"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = "simulation"

    # SQLite by default; postgres works too (psycopg driver is installed).
    DATABASE_URL: str = "sqlite:///./data/sap_change_impact.db"

    # LLM provider. "mock" = deterministic facts-only generator (no network).
    LLM_MODE: str = "mock"  # mock | openai
    LLM_BASE_URL: str = "http://localhost:8001/v1"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "deterministic-mock"

    CORS_ORIGINS: str = "http://localhost:8013,http://127.0.0.1:8013"
    LOG_LEVEL: str = "INFO"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def is_mock_llm(self) -> bool:
        return self.LLM_MODE.lower() != "openai"


@lru_cache
def get_settings() -> Settings:
    return Settings()
