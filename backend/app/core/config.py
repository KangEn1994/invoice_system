from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Invoice System"
    api_prefix: str = "/api"

    database_url: str = "postgresql+psycopg2://invoice:invoice@db:5432/invoice_system"

    secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 3650

    cors_origins: str = "*"

    bootstrap_admin_username: str = "admin"
    bootstrap_admin_password: str = "admin123456"

    files_dir: str = "/data/files"
    zip_cache_dir: str = "/data/zip_cache"

    public_share_base_url: str = "http://localhost:8080"

    ocr_use_gpu: bool = True
    ocr_lang: str = "ch"

    startup_db_max_retries: int = 60
    startup_db_retry_seconds: float = 2.0
    share_log_retention_days: int = 7
    share_log_cleanup_interval_hours: int = 24

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False)

    @property
    def cors_origin_list(self) -> list[str]:
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]

    def ensure_dirs(self) -> None:
        Path(self.files_dir).mkdir(parents=True, exist_ok=True)
        Path(self.zip_cache_dir).mkdir(parents=True, exist_ok=True)


settings = Settings()
