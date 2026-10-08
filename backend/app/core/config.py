from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "CaseVault"
    app_version: str = "0.1.0"
    debug: bool = False

    # Database
    database_url: str = "postgresql://casevault:casevault@localhost:5432/casevault"

    # Security (placeholder — filled in Day 2)
    secret_key: str = "change-me-before-production"


settings = Settings()
