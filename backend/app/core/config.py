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

    # ---- Embeddings (Day 5) ----
    # Local sentence-transformers model name.
    # Model is downloaded on first use (~90 MB for all-MiniLM-L6-v2).
    # To use a different model, also update EMBEDDING_DIM to match.
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    # Expected vector dimension for the selected embedding model.
    # Must match EMBEDDING_DIMENSION in app.models.document.
    embedding_dim: int = 384

    # Number of chunks to embed per batch. Larger = faster but more RAM.
    embedding_batch_size: int = 64

    # ---- Search (Day 5) ----
    # Default number of results returned by semantic search.
    search_default_limit: int = 10

    # Hard cap on results per search request.
    search_max_limit: int = 50

    # Maximum number of characters in a search query.
    search_max_query_length: int = 2000

    # ---- LLM provider (Day 6) ----
    # Supported: "openai" | "none"
    # "none" disables generation; the /chat/ask endpoint returns 503.
    llm_provider: str = "openai"

    # Model name passed to the provider API.
    # For OpenAI: "gpt-4o-mini" is cost-effective; "gpt-4o" is more capable.
    llm_model: str = "gpt-4o-mini"

    # API key for the LLM provider.  Never expose to the browser.
    # If unset, the backend starts but /chat/ask returns 503.
    llm_api_key: str | None = None

    # Optional custom base URL (e.g. for OpenAI-compatible endpoints).
    llm_base_url: str | None = None

    # Per-request timeout in seconds.
    llm_timeout_seconds: int = 60

    # ---- RAG (Day 6) ----
    # Maximum number of retrieved chunks to include in the LLM context.
    rag_max_context_chunks: int = 5

    # Maximum total characters of retrieved text sent to the LLM.
    rag_max_context_chars: int = 8000

    # Maximum characters in a question submitted to /chat/ask.
    rag_max_question_length: int = 2000

    # Number of conversation history messages (user+assistant pairs) to
    # include in the prompt.  Bounded to prevent unbounded context growth.
    rag_history_messages: int = 10

    # Maximum tokens the LLM should generate for an answer.
    rag_max_answer_tokens: int = 600


settings = Settings()
