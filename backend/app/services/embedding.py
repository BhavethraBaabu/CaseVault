"""
Embedding provider implementations and chunk-embedding pipeline.

Day 5 introduces two concrete providers:

  SentenceTransformerProvider
    Wraps sentence-transformers/all-MiniLM-L6-v2 (384-dim, CPU, ~90 MB).
    The model is loaded lazily on first use and cached as a process-level
    singleton to avoid repeated disk reads.

  FakeEmbeddingProvider
    Deterministic fixed-dimension vectors used in unit tests.
    Does NOT download or initialise any model.

Both satisfy the EmbeddingProvider protocol defined in embedding_provider.py.

Embedding pipeline
------------------
  embed_pending_chunks(db, provider, batch_size)
    Processes all PENDING/FAILED chunks without a valid current-model
    embedding.  Safe to call repeatedly (idempotent).  Does NOT run
    automatically at startup or on every request.

  embed_document_chunks(db, doc_id, provider)
    Embeds all chunks for a single document (called after ingestion when
    the provider is available).

Memory / CPU notes
------------------
  all-MiniLM-L6-v2 requires ~200–350 MB RAM and ~0.5–2 s per batch of 64
  chunks on CPU.  Some free-tier instances have 512 MB total RAM; verify
  before deploying.  The model is NOT pre-loaded at import time.

Do NOT log chunk content or query text.
"""

import logging
import math
import threading
import uuid

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import DocumentChunk, EmbeddingStatus
from app.services.embedding_provider import EmbeddingError, EmbeddingProvider

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Concrete provider: sentence-transformers
# ---------------------------------------------------------------------------

_MODEL_LOCK = threading.Lock()
_MODEL_SINGLETON: "SentenceTransformerProvider | None" = None


class SentenceTransformerProvider:
    """
    EmbeddingProvider backed by a local sentence-transformers model.

    The model is loaded once per process and cached.  All attributes
    are read from settings so the model name can be changed via
    environment variables without code changes.

    Args:
        model_name: HuggingFace model identifier.
        expected_dim: Expected output dimension; raises on mismatch.

    Raises:
        EmbeddingError if the model cannot be loaded.
    """

    def __init__(
        self,
        model_name: str = settings.embedding_model,
        expected_dim: int = settings.embedding_dim,
    ) -> None:
        self._model_name = model_name
        self._expected_dim = expected_dim
        self._model = None  # Loaded lazily

    def _get_model(self):
        if self._model is not None:
            return self._model
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore[import]

            self._model = SentenceTransformer(self._model_name)
        except Exception as exc:
            raise EmbeddingError(
                f"Failed to load embedding model '{self._model_name}': {exc}"
            ) from exc
        return self._model

    @property
    def dimension(self) -> int:
        return self._expected_dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        """
        Embed a batch of texts.

        Args:
            texts: Non-empty list of strings.

        Returns:
            List of float vectors, one per input.

        Raises:
            EmbeddingError for empty input or model failures.
            ValueError for dimension mismatches or non-finite values.
        """
        if not texts:
            raise EmbeddingError("embed() requires at least one text string.")
        model = self._get_model()
        try:
            vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        except Exception as exc:
            raise EmbeddingError(f"Embedding generation failed: {exc}") from exc

        result: list[list[float]] = []
        for i, vec in enumerate(vectors):
            v = [float(x) for x in vec]
            _validate_vector(v, self._expected_dim, context=f"text[{i}]")
            result.append(v)
        return result


def get_embedding_provider() -> SentenceTransformerProvider:
    """
    Return the process-level SentenceTransformerProvider singleton.

    Thread-safe.  The model is not loaded until the first call to embed().
    """
    global _MODEL_SINGLETON
    if _MODEL_SINGLETON is None:
        with _MODEL_LOCK:
            if _MODEL_SINGLETON is None:
                _MODEL_SINGLETON = SentenceTransformerProvider()
    return _MODEL_SINGLETON


# ---------------------------------------------------------------------------
# Fake provider for tests
# ---------------------------------------------------------------------------


class FakeEmbeddingProvider:
    """
    Deterministic embedding provider for unit tests.

    Returns a fixed-length vector based on the hash of the input string.
    Vectors are L2-normalised so cosine similarity is well-defined.

    Does NOT import or initialise sentence-transformers.
    """

    def __init__(self, dim: int = settings.embedding_dim) -> None:
        self._dim = dim

    @property
    def dimension(self) -> int:
        return self._dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            raise EmbeddingError("embed() requires at least one text string.")
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        if not text.strip():
            raise EmbeddingError("Cannot embed empty or whitespace-only text.")
        # Deterministic: use hash seed to fill a small-magnitude vector
        seed = hash(text) % (2**31)
        import random

        rng = random.Random(seed)
        raw = [rng.gauss(0, 1) for _ in range(self._dim)]
        norm = math.sqrt(sum(x * x for x in raw))
        if norm == 0:
            raw[0] = 1.0
            norm = 1.0
        return [x / norm for x in raw]


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _validate_vector(vec: list[float], expected_dim: int, context: str = "") -> None:
    """Raise ValueError if the vector is invalid."""
    if len(vec) != expected_dim:
        raise ValueError(
            f"Embedding dimension mismatch{(' at ' + context) if context else ''}: "
            f"expected {expected_dim}, got {len(vec)}."
        )
    if not all(math.isfinite(v) for v in vec):
        raise ValueError(
            f"Embedding contains non-finite values{(' at ' + context) if context else ''}."
        )


# ---------------------------------------------------------------------------
# Embedding pipeline
# ---------------------------------------------------------------------------


def embed_document_chunks(
    db: Session,
    doc_id: uuid.UUID,
    provider: EmbeddingProvider,
) -> int:
    """
    Embed all chunks for a single document that need (re-)embedding.

    A chunk needs embedding when:
      - Its status is not READY, OR
      - Its embedding_model does not match the current model (stale).

    Chunks already READY with the current model are skipped.
    Returns the number of chunks embedded.

    This is called synchronously after document ingestion when a provider
    is available.  For large documents this may add latency to the upload
    request; consider offloading to a background task for production.
    """
    from sqlalchemy import or_

    chunks = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.document_id == doc_id)
        .filter(
            or_(
                DocumentChunk.embedding_status != EmbeddingStatus.READY,
                DocumentChunk.embedding_model != settings.embedding_model,
                DocumentChunk.embedding_model.is_(None),
            )
        )
        .order_by(DocumentChunk.chunk_index)
        .all()
    )
    if not chunks:
        return 0
    return _embed_chunks(db, chunks, provider)


def embed_pending_chunks(
    db: Session,
    provider: EmbeddingProvider,
    batch_size: int = settings.embedding_batch_size,
) -> int:
    """
    Embed all chunks that do not yet have a valid embedding for the current model.

    Processes in batches to avoid loading all chunks into memory at once.
    Idempotent: safe to call repeatedly.
    Returns the total number of chunks successfully embedded.
    """
    total = 0
    offset = 0
    while True:
        batch = (
            db.query(DocumentChunk)
            .filter(
                DocumentChunk.embedding_model != settings.embedding_model,
            )
            .order_by(DocumentChunk.document_id, DocumentChunk.chunk_index)
            .limit(batch_size)
            .offset(offset)
            .all()
        )
        # Also include chunks with no model set (never embedded)
        if offset == 0:
            no_model = (
                db.query(DocumentChunk)
                .filter(DocumentChunk.embedding_model.is_(None))
                .order_by(DocumentChunk.document_id, DocumentChunk.chunk_index)
                .limit(batch_size)
                .all()
            )
            # Merge, avoiding duplicates
            seen_ids = {c.id for c in batch}
            batch.extend(c for c in no_model if c.id not in seen_ids)

        if not batch:
            break
        embedded = _embed_chunks(db, batch, provider)
        total += embedded
        if len(batch) < batch_size:
            break
        offset += batch_size
    return total


def _embed_chunks(
    db: Session,
    chunks: list[DocumentChunk],
    provider: EmbeddingProvider,
) -> int:
    """
    Embed a list of chunks and persist the results transactionally.

    Marks chunks PROCESSING before the API call and READY/FAILED after.
    Returns the number of chunks successfully embedded.
    """
    if not chunks:
        return 0

    # Filter out empty content
    valid = [c for c in chunks if c.content and c.content.strip()]
    for c in chunks:
        if not (c.content and c.content.strip()):
            c.embedding_status = EmbeddingStatus.FAILED
            c.embedding = None

    if not valid:
        try:
            db.commit()
        except Exception:
            db.rollback()
        return 0

    # Mark as processing
    for c in valid:
        c.embedding_status = EmbeddingStatus.PROCESSING
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    # Generate embeddings
    texts = [c.content for c in valid]
    try:
        vectors = provider.embed(texts)
    except EmbeddingError as exc:
        for c in valid:
            c.embedding_status = EmbeddingStatus.FAILED
            c.embedding = None
        try:
            db.commit()
        except Exception:
            db.rollback()
        logger.error("Embedding provider error: %s", exc)
        return 0
    except Exception as exc:
        for c in valid:
            c.embedding_status = EmbeddingStatus.FAILED
            c.embedding = None
        try:
            db.commit()
        except Exception:
            db.rollback()
        logger.error("Unexpected error during embedding: %s", exc)
        return 0

    # Validate and persist
    success = 0
    for chunk, vec in zip(valid, vectors):
        try:
            _validate_vector(vec, provider.dimension, context=str(chunk.id))
            chunk.embedding = vec
            chunk.embedding_model = settings.embedding_model
            chunk.embedding_status = EmbeddingStatus.READY
            success += 1
        except ValueError:
            chunk.embedding_status = EmbeddingStatus.FAILED
            chunk.embedding = None
            chunk.embedding_model = None

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    return success
