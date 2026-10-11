import os

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

    # Security
    secret_key: str = "change-me-before-production"
    access_token_expire_minutes: int = 30

    # Document storage
    # Path to the directory where uploaded files are stored.
    # Must be outside the application source tree and excluded from Git.
    document_storage_path: str = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "storage",
        "documents",
    )

    # Maximum upload size in bytes (default: 10 MB)
    max_upload_size_bytes: int = 10 * 1024 * 1024

    # Chunking configuration
    # Approximate target chunk size in words. Words * 1.3 ≈ tokens (estimated).
    chunk_size_words: int = 500

    # Approximate overlap in words between adjacent chunks.
    chunk_overlap_words: int = 60


settings = Settings()
