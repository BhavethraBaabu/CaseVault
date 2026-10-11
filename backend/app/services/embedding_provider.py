"""
Embedding provider abstraction — Day 4 stub.

This module defines the interface that Day 5 will implement to generate
vector embeddings for document chunks.

Current pipeline (Day 4):
    Upload → Validate → Extract → Normalize → Chunk → [Day 5: Embed] → [Day 5: Vector Search]

Day 5 will:
    1. Implement a concrete EmbeddingProvider (e.g. OpenAI, local sentence-transformers).
    2. Add an embedding column to document_chunks via a new Alembic migration.
    3. Call the provider after chunking in document processing.
    4. Implement vector similarity search using pgvector.

DO NOT generate embeddings or perform vector search in Day 4.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingProvider(Protocol):
    """
    Interface for embedding providers.

    Any object implementing this protocol can be used as an embedding backend
    without changes to the document processing pipeline.
    """

    def embed(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embedding vectors for a list of text strings.

        Args:
            texts: Non-empty list of text strings to embed.

        Returns:
            List of float vectors, one per input text.
            All vectors must have the same dimension.

        Raises:
            EmbeddingError for provider-level failures.
        """
        ...

    @property
    def dimension(self) -> int:
        """Return the embedding vector dimension for this provider."""
        ...


class EmbeddingError(Exception):
    """Raised by embedding providers for provider-level failures."""


class NoOpEmbeddingProvider:
    """
    Stub provider used in Day 4.

    Raises NotImplementedError on any call to make clear that
    embedding is not yet implemented.
    """

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError(
            "Embedding generation is not implemented until Day 5. "
            "Use a concrete EmbeddingProvider implementation."
        )

    @property
    def dimension(self) -> int:
        raise NotImplementedError("Embedding dimension is not defined until Day 5.")
