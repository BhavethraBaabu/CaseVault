"""
Concrete LLM provider — OpenAI-compatible API.

Uses the official openai Python SDK (v1.x).  Because the SDK supports a
custom base_url, this provider also works with any OpenAI-compatible
endpoint (e.g. local servers, Azure OpenAI).

Configuration (via environment / .env):
    LLM_PROVIDER     "openai" | "none"
    LLM_MODEL        model name, e.g. "gpt-4o-mini" or "gpt-4o"
    LLM_API_KEY      secret key — never expose to the browser
    LLM_BASE_URL     optional custom endpoint
    LLM_TIMEOUT_SECONDS  per-request timeout (default 60)

Free-tier notes
---------------
  gpt-4o-mini (OpenAI) offers a modest free trial credit; thereafter it
  costs roughly $0.15 / 1M input tokens.  This is NOT free indefinitely.
  Verify your account's billing settings before running in production.

  If LLM_API_KEY is not set, get_llm_provider() raises LLMError so the
  backend starts cleanly but /chat/ask returns HTTP 503.

Security
--------
  - API key is read from settings; never passed through the API layer.
  - Full prompts (containing retrieved document text) are NOT logged.
  - Stack traces and openai error details are caught; only a safe
    generic message is returned to the client.
"""

import logging
import threading

from app.core.config import settings
from app.services.llm_provider import LLMError, LLMProvider

logger = logging.getLogger(__name__)

_PROVIDER_LOCK = threading.Lock()
_PROVIDER_SINGLETON: "OpenAIProvider | None" = None


class OpenAIProvider:
    """
    LLM provider backed by the OpenAI chat completions API.

    The underlying openai.OpenAI client is created once and reused.

    Args:
        api_key:    API key for authentication.
        model:      Model name (e.g. "gpt-4o-mini").
        base_url:   Optional custom base URL.
        timeout:    Per-request timeout in seconds.

    Raises:
        LLMError on generation failure.
    """

    def __init__(
        self,
        api_key: str,
        model: str = settings.llm_model,
        base_url: str | None = settings.llm_base_url,
        timeout: int = settings.llm_timeout_seconds,
    ) -> None:
        self._model = model
        self._timeout = timeout
        try:
            from openai import OpenAI  # type: ignore[import]

            kwargs: dict = {"api_key": api_key, "timeout": float(timeout)}
            if base_url:
                kwargs["base_url"] = base_url
            self._client = OpenAI(**kwargs)
        except Exception as exc:
            raise LLMError(f"Failed to initialise LLM provider: {exc}") from exc

    def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, str]],
        max_tokens: int = settings.rag_max_answer_tokens,
    ) -> str:
        """
        Generate a response via the OpenAI chat completions API.

        Args:
            system_prompt:  System instruction (contains evidence context).
            messages:       Conversation turns; last entry is the user question.
            max_tokens:     Maximum tokens for the generated answer.

        Returns:
            Generated answer text.

        Raises:
            LLMError for all API failures (timeout, rate limit, auth, etc.).
        """
        api_messages = [{"role": "system", "content": system_prompt}] + messages
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=api_messages,  # type: ignore[arg-type]
                max_tokens=max_tokens,
            )
            content = response.choices[0].message.content
            if content is None:
                raise LLMError("LLM returned an empty response.")
            return content
        except LLMError:
            raise
        except Exception as exc:
            # Catch all SDK errors; do not surface internal details
            raise LLMError("LLM generation failed. Please try again.") from exc


def get_llm_provider() -> LLMProvider:
    """
    Return the process-level LLM provider singleton.

    Thread-safe.  Raises LLMError if the provider is not configured.

    Raises:
        LLMError if LLM_PROVIDER is "none" or LLM_API_KEY is not set.
    """
    global _PROVIDER_SINGLETON
    if _PROVIDER_SINGLETON is not None:
        return _PROVIDER_SINGLETON
    with _PROVIDER_LOCK:
        if _PROVIDER_SINGLETON is not None:
            return _PROVIDER_SINGLETON
        if settings.llm_provider == "none":
            raise LLMError(
                "LLM provider is disabled (LLM_PROVIDER=none). "
                "Set LLM_PROVIDER=openai and LLM_API_KEY to enable chat."
            )
        if not settings.llm_api_key:
            raise LLMError(
                "LLM_API_KEY is not configured. "
                "Set LLM_API_KEY in your .env file to enable the chat feature."
            )
        _PROVIDER_SINGLETON = OpenAIProvider(api_key=settings.llm_api_key)
    return _PROVIDER_SINGLETON
