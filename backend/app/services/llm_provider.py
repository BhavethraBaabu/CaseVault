"""
LLM provider abstraction — Day 6.

Defines the LLMProvider protocol and helpers shared by all providers.

Providers
---------
  OpenAIProvider   — concrete provider using the openai SDK
                     (see llm.py)
  FakeLLMProvider  — deterministic, test-only; no network calls
  LLMError         — raised by providers for all generation failures

Security rules
--------------
  - Never log full prompts that contain retrieved document text.
  - Never expose API keys to the browser or in API responses.
  - Never trust model-generated citation IDs without application-side
    validation against the authorised retrieval set.
"""

from typing import Protocol, runtime_checkable


class LLMError(Exception):
    """Raised by LLM providers for provider-level failures."""


@runtime_checkable
class LLMProvider(Protocol):
    """
    Interface for language-model generation providers.

    Any object implementing this protocol can be used as the generation
    backend for the RAG service without changes to the pipeline.
    """

    def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, str]],
        max_tokens: int = 600,
    ) -> str:
        """
        Generate a text response.

        Args:
            system_prompt: The system instruction (contains evidence).
            messages:       Conversation history as list of
                            {"role": "user"|"assistant", "content": "..."}.
                            The last element is the current user turn.
            max_tokens:     Maximum tokens to generate.

        Returns:
            Generated text string.

        Raises:
            LLMError for provider-level failures (timeout, rate limit, etc.).
        """
        ...


class FakeLLMProvider:
    """
    Deterministic LLM provider for unit tests.

    Does NOT make any network calls.  Records the most recent call for
    assertion in isolation tests.

    Args:
        response:       Text to return from every generate() call.
        raise_error:    If True, raise LLMError instead of returning.
    """

    def __init__(
        self,
        response: str = "[SOURCE:1] The document states the relevant information.",
        raise_error: bool = False,
    ) -> None:
        self._response = response
        self._raise_error = raise_error
        # Recorded for inspection in tests
        self.last_system_prompt: str | None = None
        self.last_messages: list[dict[str, str]] | None = None
        self.call_count: int = 0

    def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, str]],
        max_tokens: int = 600,
    ) -> str:
        self.last_system_prompt = system_prompt
        self.last_messages = list(messages)
        self.call_count += 1
        if self._raise_error:
            raise LLMError("Fake provider error (raise_error=True)")
        return self._response


class FakeSequentialProvider:
    """
    Deterministic LLM provider that returns responses from a pre-configured
    sequence.  Used for agent tests that require multiple round-trips.

    When the sequence is exhausted, the last response is returned for all
    subsequent calls.

    Args:
        responses:  Ordered list of strings to return from generate().
        raise_on:   If given, raise LLMError on this 1-based call index.
    """

    def __init__(
        self,
        responses: list[str],
        raise_on: int | None = None,
    ) -> None:
        if not responses:
            responses = ['{"type": "answer", "content": "No response configured."}']
        self._responses = responses
        self._raise_on = raise_on
        self._index = 0
        self.call_count: int = 0
        # Full call log for assertions
        self.call_log: list[dict] = []

    def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, str]],
        max_tokens: int = 600,
    ) -> str:
        self.call_count += 1
        self.call_log.append(
            {"system_prompt": system_prompt, "messages": list(messages)}
        )
        if self._raise_on is not None and self.call_count == self._raise_on:
            raise LLMError(f"Fake provider error on call {self.call_count}")
        resp = self._responses[self._index]
        # Advance index but clamp at last entry
        self._index = min(self._index + 1, len(self._responses) - 1)
        return resp
