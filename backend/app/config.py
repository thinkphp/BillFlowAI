from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://invoice:invoice@localhost:5432/invoices"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    frontend_origin: str = "http://localhost:5173"
    max_upload_size_mb: int = 15
    minimum_confidence: float = 0.75

    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")


settings = Settings()
