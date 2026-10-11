"""
Tests for Day 5 embedding provider and pipeline.

All tests use FakeEmbeddingProvider — no sentence-transformers model
is downloaded or initialised.

Coverage:
  1.  FakeEmbeddingProvider returns correct dimension.
  2.  Empty input raises EmbeddingError.
  3.  Whitespace-only input raises EmbeddingError.
  4.  Batch length matches input length.
  5.  Vectors are normalised (unit length within float tolerance).
  6.  Invalid dimension raises ValueError.
  7.  Non-finite values raise ValueError.
  8.  SentenceTransformerProvider is NOT imported during tests.
  9.  Chunk without embedding is embedded and marked READY.
  10. Chunk with valid current-model embedding is skipped.
  11. Chunk with a different model is re-embedded.
  12. Failed embedding generation marks chunk FAILED and can be retried.
  13. Running pipeline twice does not duplicate chunks.
  14. Document/chunk metadata is intact after embedding.
  15. Batch with empty dataset returns 0.
  16. Content-less chunk is marked FAILED gracefully.
"""

import math
import uuid

import pytest

from app.models.case_membership import CaseMemberRole
from app.models.document import DocumentChunk, EmbeddingStatus
from app.models.user import UserRole
from app.services.embedding import FakeEmbeddingProvider, _embed_chunks, _validate_vector
from app.services.embedding_provider import EmbeddingError
from app.services.storage import LocalStorage, set_storage
from tests.helpers import add_membership, make_case, make_client, make_user

# ---------------------------------------------------------------------------
# Storage fixture (required by upload helpers used in pipeline tests)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def temp_storage(tmp_path):
    storage = LocalStorage(str(tmp_path / "storage"))
    set_storage(storage)
    yield storage
    set_storage(None)


# ---------------------------------------------------------------------------
# FakeEmbeddingProvider unit tests
# ---------------------------------------------------------------------------


def test_fake_provider_correct_dimension():
    """1. FakeEmbeddingProvider returns the configured dimension."""
    provider = FakeEmbeddingProvider(dim=16)
    vecs = provider.embed(["hello"])
    assert len(vecs) == 1
    assert len(vecs[0]) == 16


def test_fake_provider_empty_list_raises():
    """2. Empty input raises EmbeddingError."""
    provider = FakeEmbeddingProvider(dim=16)
    with pytest.raises(EmbeddingError):
        provider.embed([])


def test_fake_provider_whitespace_raises():
    """3. Whitespace-only text raises EmbeddingError."""
    provider = FakeEmbeddingProvider(dim=16)
    with pytest.raises(EmbeddingError):
        provider.embed(["   "])


def test_fake_provider_batch_length_matches():
    """4. Batch output length equals input length."""
    provider = FakeEmbeddingProvider(dim=16)
    texts = ["alpha", "beta", "gamma"]
    vecs = provider.embed(texts)
    assert len(vecs) == len(texts)


def test_fake_provider_vectors_normalised():
    """5. Vectors are unit-length (L2 norm ≈ 1)."""
    provider = FakeEmbeddingProvider(dim=32)
    vecs = provider.embed(["normalise me"])
    norm = math.sqrt(sum(v * v for v in vecs[0]))
    assert abs(norm - 1.0) < 1e-6


def test_fake_provider_deterministic():
    """Same input produces identical vectors."""
    provider = FakeEmbeddingProvider(dim=32)
    v1 = provider.embed(["same text"])[0]
    v2 = provider.embed(["same text"])[0]
    assert v1 == v2


def test_validate_vector_wrong_dimension():
    """6. Wrong dimension raises ValueError."""
    with pytest.raises(ValueError, match="dimension mismatch"):
        _validate_vector([0.1, 0.2], expected_dim=3)


def test_validate_vector_non_finite():
    """7. Non-finite values raise ValueError."""
    import math as _math

    with pytest.raises(ValueError, match="non-finite"):
        _validate_vector([0.1, _math.nan, 0.3], expected_dim=3)


def test_sentence_transformer_not_imported_in_tests():
    """8. SentenceTransformerProvider is not imported by test infrastructure."""
    import sys

    assert "sentence_transformers" not in sys.modules


# ---------------------------------------------------------------------------
# Embedding pipeline tests (use FakeEmbeddingProvider + SQLite)
# ---------------------------------------------------------------------------


def _make_chunk(
    db, doc_id: uuid.UUID, index: int = 0, content: str = "hello world"
) -> DocumentChunk:
    chunk = DocumentChunk(
        document_id=doc_id,
        chunk_index=index,
        content=content,
        embedding_status=EmbeddingStatus.PENDING,
    )
    db.add(chunk)
    db.commit()
    db.refresh(chunk)
    return chunk


def _make_doc(db) -> uuid.UUID:
    """Create minimal document record for testing pipeline (bypasses upload)."""
    from app.models.document import Document, DocumentStatus

    cl = make_client(db)
    case = make_case(db, cl)
    owner = make_user(db, role=UserRole.LAWYER)
    add_membership(db, case, owner, CaseMemberRole.OWNER)

    import hashlib

    content = b"test content"
    doc = Document(
        case_id=case.id,
        uploaded_by=owner.id,
        original_filename="test.txt",
        storage_key=f"{case.id}/{uuid.uuid4()}",
        content_type="text/plain",
        file_size=len(content),
        file_hash=hashlib.sha256(content).hexdigest(),
        status=DocumentStatus.READY,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc.id


def test_chunk_without_embedding_is_embedded(db_session):
    """9. A PENDING chunk gets embedded and marked READY."""
    doc_id = _make_doc(db_session)
    chunk = _make_chunk(db_session, doc_id, content="legal termination clause")
    provider = FakeEmbeddingProvider(dim=384)

    from app.services.embedding import embed_document_chunks

    count = embed_document_chunks(db_session, doc_id, provider)

    assert count == 1
    db_session.refresh(chunk)
    assert chunk.embedding is not None
    assert len(chunk.embedding) == 384
    assert chunk.embedding_status == EmbeddingStatus.READY
    assert chunk.embedding_model is not None


def test_chunk_with_current_model_is_skipped(db_session):
    """10. A chunk already embedded with the current model is not re-embedded."""
    from app.core.config import settings

    doc_id = _make_doc(db_session)
    chunk = _make_chunk(db_session, doc_id, content="pre-embedded content")
    provider = FakeEmbeddingProvider(dim=384)

    # Pre-populate embedding
    chunk.embedding = [0.0] * 384
    chunk.embedding_model = settings.embedding_model
    chunk.embedding_status = EmbeddingStatus.READY
    db_session.commit()

    from app.services.embedding import embed_document_chunks

    count = embed_document_chunks(db_session, doc_id, provider)

    assert count == 0
    db_session.refresh(chunk)
    assert chunk.embedding == [0.0] * 384  # unchanged


def test_stale_model_triggers_reembed(db_session):
    """11. Chunk with a different model name is re-embedded."""
    doc_id = _make_doc(db_session)
    chunk = _make_chunk(db_session, doc_id, content="stale model text")
    provider = FakeEmbeddingProvider(dim=384)

    chunk.embedding = [0.0] * 384
    chunk.embedding_model = "old-model/deprecated"
    chunk.embedding_status = EmbeddingStatus.READY
    db_session.commit()

    from app.services.embedding import embed_document_chunks

    count = embed_document_chunks(db_session, doc_id, provider)

    assert count == 1
    db_session.refresh(chunk)
    assert chunk.embedding != [0.0] * 384  # changed


def test_failed_embedding_can_be_retried(db_session):
    """12. A FAILED chunk can be retried and will be embedded."""
    doc_id = _make_doc(db_session)
    chunk = _make_chunk(db_session, doc_id, content="retry this chunk")
    chunk.embedding_status = EmbeddingStatus.FAILED
    db_session.commit()

    provider = FakeEmbeddingProvider(dim=384)
    from app.services.embedding import embed_document_chunks

    count = embed_document_chunks(db_session, doc_id, provider)

    assert count == 1
    db_session.refresh(chunk)
    assert chunk.embedding_status == EmbeddingStatus.READY


def test_pipeline_twice_does_not_duplicate_chunks(db_session):
    """13. Running embed_document_chunks twice does not create duplicate chunks."""
    doc_id = _make_doc(db_session)
    _make_chunk(db_session, doc_id, content="no duplicates please")
    provider = FakeEmbeddingProvider(dim=384)

    from app.services.embedding import embed_document_chunks

    embed_document_chunks(db_session, doc_id, provider)
    embed_document_chunks(db_session, doc_id, provider)

    count = db_session.query(DocumentChunk).filter_by(document_id=doc_id).count()
    assert count == 1


def test_metadata_intact_after_embedding(db_session):
    """14. Document/chunk content and page_number are unchanged after embedding."""
    doc_id = _make_doc(db_session)
    chunk = _make_chunk(db_session, doc_id, content="important legal text", index=2)
    chunk.page_number = 3
    db_session.commit()

    provider = FakeEmbeddingProvider(dim=384)
    from app.services.embedding import embed_document_chunks

    embed_document_chunks(db_session, doc_id, provider)

    db_session.refresh(chunk)
    assert chunk.content == "important legal text"
    assert chunk.chunk_index == 2
    assert chunk.page_number == 3


def test_embed_pending_chunks_empty_dataset(db_session):
    """15. embed_pending_chunks on empty dataset returns 0."""
    from app.services.embedding import embed_pending_chunks

    provider = FakeEmbeddingProvider(dim=384)
    count = embed_pending_chunks(db_session, provider)
    assert count == 0


def test_empty_content_chunk_marked_failed(db_session):
    """16. A chunk with empty/whitespace content is marked FAILED gracefully."""
    doc_id = _make_doc(db_session)
    chunk = _make_chunk(db_session, doc_id, content="   ")
    provider = FakeEmbeddingProvider(dim=384)

    _embed_chunks(db_session, [chunk], provider)

    db_session.refresh(chunk)
    assert chunk.embedding_status == EmbeddingStatus.FAILED
    assert chunk.embedding is None
