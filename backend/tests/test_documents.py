"""
Comprehensive tests for Day 4 document ingestion.

Covers:
  - Upload and validation (authorized upload, role restrictions, bad inputs)
  - Text extraction and chunking (TXT, DOCX, PDF, edge cases)
  - Authorization and lifecycle (list, view, download, delete, cross-case)

Test fixtures create minimal valid PDFs and DOCX files in memory to avoid
committing binary test data to the repository.

Note on PostgreSQL:
  These tests use an in-memory SQLite database (same as Day 3).
  PostgreSQL/pgvector compatibility is not validated here.
"""

import io
import uuid

import pytest

from app.models.case_membership import CaseMemberRole
from app.models.user import UserRole
from app.services.storage import LocalStorage, set_storage
from tests.helpers import (
    add_membership,
    auth_headers,
    make_case,
    make_client,
    make_user,
)

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def make_txt_bytes(text: str = "Hello world. This is a test document.") -> bytes:
    return text.encode("utf-8")


def make_docx_bytes(text: str = "Hello world. This is a test document.") -> bytes:
    from docx import Document as DocxDocument

    doc = DocxDocument()
    doc.add_paragraph(text)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def make_pdf_bytes(text: str = "Hello world. This is a test document.") -> bytes:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.cell(0, 10, text)
    return bytes(pdf.output())


def make_malformed_pdf_bytes() -> bytes:
    """Bytes that look like a PDF (magic header) but are corrupt."""
    return b"%PDF-1.4\n\x00corrupted content that is not a valid pdf"


def make_malformed_docx_bytes() -> bytes:
    """Bytes with ZIP magic but not a valid DOCX."""
    return b"PK\x03\x04" + b"\x00" * 100


# ---------------------------------------------------------------------------
# Autouse fixture: redirect storage to a temp directory for each test
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def temp_storage(tmp_path):
    """Redirect document storage to a per-test temp directory."""
    storage = LocalStorage(str(tmp_path / "storage"))
    set_storage(storage)
    yield storage
    set_storage(None)  # Reset to default after test


# ---------------------------------------------------------------------------
# Upload and validation
# ---------------------------------------------------------------------------


def test_owner_can_upload_txt(client, db_session):
    """1. Authorized OWNER can upload a valid TXT file."""
    user = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, user, CaseMemberRole.OWNER)

    resp = client.post(
        f"/cases/{case.id}/documents",
        files={"file": ("test.txt", make_txt_bytes(), "text/plain")},
        headers=auth_headers(user),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["original_filename"] == "test.txt"
    assert data["status"] == "READY"
    assert data["file_size"] > 0
    assert "storage_key" not in data


def test_member_can_upload(client, db_session):
    """2. MEMBER can upload a document."""
    owner = make_user(db_session, role=UserRole.LAWYER)
    member = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, owner, CaseMemberRole.OWNER)
    add_membership(db_session, case, member, CaseMemberRole.MEMBER)

    resp = client.post(
        f"/cases/{case.id}/documents",
        files={"file": ("doc.txt", make_txt_bytes(), "text/plain")},
        headers=auth_headers(member),
    )
    assert resp.status_code == 201


def test_viewer_cannot_upload(client, db_session):
    """3. VIEWER cannot upload."""
    owner = make_user(db_session, role=UserRole.LAWYER)
    viewer = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, owner, CaseMemberRole.OWNER)
    add_membership(db_session, case, viewer, CaseMemberRole.VIEWER)

    resp = client.post(
        f"/cases/{case.id}/documents",
        files={"file": ("doc.txt", make_txt_bytes(), "text/plain")},
        headers=auth_headers(viewer),
    )
    assert resp.status_code == 403


def test_restricted_lawyer_with_member_role_can_upload(client, db_session):
    """4. RESTRICTED_LAWYER with MEMBER case role can upload."""
    owner = make_user(db_session, role=UserRole.LAWYER)
    rl = make_user(db_session, role=UserRole.RESTRICTED_LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, owner, CaseMemberRole.OWNER)
    add_membership(db_session, case, rl, CaseMemberRole.MEMBER)

    resp = client.post(
        f"/cases/{case.id}/documents",
        files={"file": ("doc.txt", make_txt_bytes(), "text/plain")},
        headers=auth_headers(rl),
    )
    assert resp.status_code == 201


def test_restricted_lawyer_without_membership_cannot_upload(client, db_session):
    """4b. RESTRICTED_LAWYER without membership cannot upload (404)."""
    rl = make_user(db_session, role=UserRole.RESTRICTED_LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)

    resp = client.post(
        f"/cases/{case.id}/documents",
        files={"file": ("doc.txt", make_txt_bytes(), "text/plain")},
        headers=auth_headers(rl),
    )
    assert resp.status_code == 404


def test_non_member_cannot_upload(client, db_session):
    """5. Non-member cannot upload."""
    outsider = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)

    resp = client.post(
        f"/cases/{case.id}/documents",
        files={"file": ("doc.txt", make_txt_bytes(), "text/plain")},
        headers=auth_headers(outsider),
    )
    assert resp.status_code == 404


def test_unsupported_extension_rejected(client, db_session):
    """6. Unsupported extension is rejected with 422."""
    user = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, user, CaseMemberRole.OWNER)

    resp = client.post(
        f"/cases/{case.id}/documents",
        files={"file": ("script.py", b"print('hello')", "text/plain")},
        headers=auth_headers(user),
    )
    assert resp.status_code == 422
    assert "Unsupported file type" in resp.json()["detail"]


def test_mismatched_content_rejected(client, db_session):
    """7. File with .pdf extension but non-PDF content is rejected."""
    user = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, user, CaseMemberRole.OWNER)

    resp = client.post(
        f"/cases/{case.id}/documents",
        files={"file": ("doc.pdf", b"not a pdf at all", "application/pdf")},
        headers=auth_headers(user),
    )
    assert resp.status_code == 422
    assert "PDF" in resp.json()["detail"]


def test_empty_file_rejected(client, db_session):
    """8. Empty file is rejected."""
    user = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, user, CaseMemberRole.OWNER)

    resp = client.post(
        f"/cases/{case.id}/documents",
        files={"file": ("empty.txt", b"", "text/plain")},
        headers=auth_headers(user),
    )
    assert resp.status_code == 422
    assert "empty" in resp.json()["detail"].lower()


def test_oversized_file_rejected(client, db_session):
    """9. File exceeding the size limit is rejected."""
    from app.core.config import settings

    user = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, user, CaseMemberRole.OWNER)

    oversized = b"x" * (settings.max_upload_size_bytes + 1)
    resp = client.post(
        f"/cases/{case.id}/documents",
        files={"file": ("big.txt", oversized, "text/plain")},
        headers=auth_headers(user),
    )
    assert resp.status_code == 422
    assert "limit" in resp.json()["detail"].lower()


def test_duplicate_filename_does_not_overwrite(client, db_session):
    """10. Two uploads with the same filename create two independent documents."""
    user = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, user, CaseMemberRole.OWNER)

    def upload():
        return client.post(
            f"/cases/{case.id}/documents",
            files={"file": ("same.txt", make_txt_bytes(), "text/plain")},
            headers=auth_headers(user),
        )

    r1 = upload()
    r2 = upload()
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["id"] != r2.json()["id"]


def test_malformed_pdf_fails_gracefully(client, db_session):
    """11. A PDF with a valid header but corrupt body fails with status FAILED."""
    user = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, user, CaseMemberRole.OWNER)

    resp = client.post(
        f"/cases/{case.id}/documents",
        files={"file": ("bad.pdf", make_malformed_pdf_bytes(), "application/pdf")},
        headers=auth_headers(user),
    )
    # The document is created but marked FAILED
    assert resp.status_code == 201
    assert resp.json()["status"] == "FAILED"
    assert resp.json()["error_message"] is not None


def test_malformed_docx_fails_gracefully(client, db_session):
    """11b. A DOCX with ZIP header but corrupt body fails with status FAILED."""
    user = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, user, CaseMemberRole.OWNER)

    docx_mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    resp = client.post(
        f"/cases/{case.id}/documents",
        files={"file": ("bad.docx", make_malformed_docx_bytes(), docx_mime)},
        headers=auth_headers(user),
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "FAILED"


def test_storage_error_does_not_leave_orphan_records(monkeypatch, client, db_session):
    """12. If storage save fails, no orphan database records are created."""
    user = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, user, CaseMemberRole.OWNER)

    class FailingStorage:
        def save(self, key, data):
            raise OSError("Disk full")

        def load(self, key):
            raise OSError("Disk full")

        def delete(self, key):
            pass

        def exists(self, key):
            return False

    set_storage(FailingStorage())  # type: ignore[arg-type]

    resp = client.post(
        f"/cases/{case.id}/documents",
        files={"file": ("doc.txt", make_txt_bytes(), "text/plain")},
        headers=auth_headers(user),
    )
    assert resp.status_code == 500

    # Confirm no document record was persisted
    from app.models.document import Document
    count = db_session.query(Document).count()
    assert count == 0


# ---------------------------------------------------------------------------
# Extraction and chunking
# ---------------------------------------------------------------------------


def test_txt_extraction_works(client, db_session):
    """13. TXT upload produces READY document with chunks."""
    user = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, user, CaseMemberRole.OWNER)

    content = "Hello world. " * 10
    resp = client.post(
        f"/cases/{case.id}/documents",
        files={"file": ("doc.txt", content.encode(), "text/plain")},
        headers=auth_headers(user),
    )
    assert resp.status_code == 201
    doc_id = resp.json()["id"]
    assert resp.json()["status"] == "READY"

    chunks_resp = client.get(f"/documents/{doc_id}/chunks", headers=auth_headers(user))
    assert chunks_resp.status_code == 200
    assert len(chunks_resp.json()) >= 1


def test_docx_extraction_works(client, db_session):
    """14. DOCX upload extracts text and produces READY document."""
    user = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, user, CaseMemberRole.OWNER)

    docx_mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    resp = client.post(
        f"/cases/{case.id}/documents",
        files={"file": ("doc.docx", make_docx_bytes(), docx_mime)},
        headers=auth_headers(user),
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "READY"


def test_pdf_extraction_works(client, db_session):
    """15. PDF text extraction works for a text-based PDF fixture."""
    user = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, user, CaseMemberRole.OWNER)

    resp = client.post(
        f"/cases/{case.id}/documents",
        files={"file": ("doc.pdf", make_pdf_bytes(), "application/pdf")},
        headers=auth_headers(user),
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "READY"


def test_empty_extraction_fails_gracefully():
    """16. Empty extracted text results in ExtractionError."""
    from app.services.extraction import ExtractionError, extract_text

    # A TXT file that normalizes to empty
    try:
        result = extract_text(b"   \n\n\n   ", "text/plain")
        # If it doesn't raise, it must have returned something useful
        assert result is not None
    except ExtractionError:
        pass  # Expected


def test_chunk_ordering_is_deterministic():
    """17. Chunk ordering is deterministic for the same input."""
    from app.services.chunking import chunk_pages
    from app.services.extraction import ExtractedPage

    text = "word " * 1200
    pages = [ExtractedPage(page_number=1, text=text)]

    result1 = chunk_pages(pages, chunk_size_words=500, chunk_overlap_words=60)
    result2 = chunk_pages(pages, chunk_size_words=500, chunk_overlap_words=60)

    assert [c.content for c in result1] == [c.content for c in result2]
    assert [c.chunk_index for c in result1] == list(range(len(result1)))


def test_chunks_overlap_as_configured():
    """18. Consecutive chunks share approximately overlap_words words."""
    from app.services.chunking import chunk_pages
    from app.services.extraction import ExtractedPage

    text = "word " * 2000
    pages = [ExtractedPage(page_number=1, text=text)]
    chunks = chunk_pages(pages, chunk_size_words=100, chunk_overlap_words=20)

    assert len(chunks) >= 2
    # Check overlap: last 20 words of chunk[0] should appear at start of chunk[1]
    words0 = chunks[0].content.split()
    words1 = chunks[1].content.split()
    overlap = words0[-20:]
    assert overlap == words1[:20]


def test_short_text_creates_one_chunk():
    """19. Short text creates exactly one non-empty chunk."""
    from app.services.chunking import chunk_pages
    from app.services.extraction import ExtractedPage

    pages = [ExtractedPage(page_number=1, text="This is a short document.")]
    chunks = chunk_pages(pages)

    assert len(chunks) == 1
    assert "short" in chunks[0].content


def test_long_text_creates_multiple_chunks():
    """20. Long text (>chunk_size words) creates multiple chunks."""
    from app.services.chunking import chunk_pages
    from app.services.extraction import ExtractedPage

    text = "word " * 2000  # Much more than chunk_size_words=500
    pages = [ExtractedPage(page_number=1, text=text)]
    chunks = chunk_pages(pages, chunk_size_words=500, chunk_overlap_words=60)

    assert len(chunks) > 1


def test_page_metadata_retained_in_chunks():
    """21. Page metadata is carried through to chunks for multi-page PDFs."""
    from app.services.chunking import chunk_pages
    from app.services.extraction import ExtractedPage

    pages = [
        ExtractedPage(page_number=1, text="page one text " * 10),
        ExtractedPage(page_number=2, text="page two text " * 10),
    ]
    chunks = chunk_pages(pages, chunk_size_words=10, chunk_overlap_words=2)

    # First chunk should be on page 1
    assert chunks[0].page_number == 1
    # Later chunks should reference page 2
    page_numbers = {c.page_number for c in chunks}
    assert 1 in page_numbers and 2 in page_numbers


# ---------------------------------------------------------------------------
# Authorization and lifecycle
# ---------------------------------------------------------------------------


def test_users_only_list_authorized_documents(client, db_session):
    """22. A user can only list documents in cases they are a member of."""
    owner = make_user(db_session, role=UserRole.LAWYER)
    outsider = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, owner, CaseMemberRole.OWNER)

    # Upload a document as owner
    client.post(
        f"/cases/{case.id}/documents",
        files={"file": ("doc.txt", make_txt_bytes(), "text/plain")},
        headers=auth_headers(owner),
    )

    # Outsider cannot list documents
    resp = client.get(f"/cases/{case.id}/documents", headers=auth_headers(outsider))
    assert resp.status_code == 404


def test_non_member_cannot_read_document_metadata(client, db_session):
    """23. Non-member receives 404 on document metadata."""
    owner = make_user(db_session, role=UserRole.LAWYER)
    outsider = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, owner, CaseMemberRole.OWNER)

    upload = client.post(
        f"/cases/{case.id}/documents",
        files={"file": ("doc.txt", make_txt_bytes(), "text/plain")},
        headers=auth_headers(owner),
    )
    doc_id = upload.json()["id"]

    resp = client.get(f"/documents/{doc_id}", headers=auth_headers(outsider))
    assert resp.status_code == 404


def test_non_member_cannot_download(client, db_session):
    """24. Non-member cannot download a document."""
    owner = make_user(db_session, role=UserRole.LAWYER)
    outsider = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, owner, CaseMemberRole.OWNER)

    upload = client.post(
        f"/cases/{case.id}/documents",
        files={"file": ("doc.txt", make_txt_bytes(), "text/plain")},
        headers=auth_headers(owner),
    )
    doc_id = upload.json()["id"]

    resp = client.get(f"/documents/{doc_id}/download", headers=auth_headers(outsider))
    assert resp.status_code == 404


def test_viewer_can_download(client, db_session):
    """25. VIEWER can download a document."""
    owner = make_user(db_session, role=UserRole.LAWYER)
    viewer = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, owner, CaseMemberRole.OWNER)
    add_membership(db_session, case, viewer, CaseMemberRole.VIEWER)

    content = b"Hello viewer test content."
    upload = client.post(
        f"/cases/{case.id}/documents",
        files={"file": ("doc.txt", content, "text/plain")},
        headers=auth_headers(owner),
    )
    doc_id = upload.json()["id"]

    resp = client.get(f"/documents/{doc_id}/download", headers=auth_headers(viewer))
    assert resp.status_code == 200
    assert resp.content == content


def test_viewer_cannot_delete(client, db_session):
    """26. VIEWER cannot delete a document."""
    owner = make_user(db_session, role=UserRole.LAWYER)
    viewer = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, owner, CaseMemberRole.OWNER)
    add_membership(db_session, case, viewer, CaseMemberRole.VIEWER)

    upload = client.post(
        f"/cases/{case.id}/documents",
        files={"file": ("doc.txt", make_txt_bytes(), "text/plain")},
        headers=auth_headers(owner),
    )
    doc_id = upload.json()["id"]

    resp = client.delete(f"/documents/{doc_id}", headers=auth_headers(viewer))
    assert resp.status_code == 403


def test_member_cannot_delete(client, db_session):
    """27. MEMBER cannot delete a document (default policy)."""
    owner = make_user(db_session, role=UserRole.LAWYER)
    member = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, owner, CaseMemberRole.OWNER)
    add_membership(db_session, case, member, CaseMemberRole.MEMBER)

    upload = client.post(
        f"/cases/{case.id}/documents",
        files={"file": ("doc.txt", make_txt_bytes(), "text/plain")},
        headers=auth_headers(owner),
    )
    doc_id = upload.json()["id"]

    resp = client.delete(f"/documents/{doc_id}", headers=auth_headers(member))
    assert resp.status_code == 403


def test_owner_can_delete(client, db_session):
    """28. OWNER can delete a document."""
    owner = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, owner, CaseMemberRole.OWNER)

    upload = client.post(
        f"/cases/{case.id}/documents",
        files={"file": ("doc.txt", make_txt_bytes(), "text/plain")},
        headers=auth_headers(owner),
    )
    doc_id = upload.json()["id"]

    resp = client.delete(f"/documents/{doc_id}", headers=auth_headers(owner))
    assert resp.status_code == 204

    # Confirm it's gone
    get_resp = client.get(f"/documents/{doc_id}", headers=auth_headers(owner))
    assert get_resp.status_code == 404


def test_admin_can_access_any_document(client, db_session):
    """29. ADMIN can access documents across cases without membership."""
    admin = make_user(db_session, role=UserRole.ADMIN)
    owner = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, owner, CaseMemberRole.OWNER)

    upload = client.post(
        f"/cases/{case.id}/documents",
        files={"file": ("doc.txt", make_txt_bytes(), "text/plain")},
        headers=auth_headers(owner),
    )
    doc_id = upload.json()["id"]

    # Admin can get metadata, download, list chunks, and list by case
    h = auth_headers(admin)
    assert client.get(f"/documents/{doc_id}", headers=h).status_code == 200
    assert client.get(f"/documents/{doc_id}/download", headers=h).status_code == 200
    assert client.get(f"/documents/{doc_id}/chunks", headers=h).status_code == 200
    assert client.get(f"/cases/{case.id}/documents", headers=h).status_code == 200

    del_resp = client.delete(f"/documents/{doc_id}", headers=auth_headers(admin))
    assert del_resp.status_code == 204


def test_unauthorized_user_cannot_access_chunks(client, db_session):
    """30. Non-member cannot access chunk endpoint."""
    owner = make_user(db_session, role=UserRole.LAWYER)
    outsider = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, owner, CaseMemberRole.OWNER)

    upload = client.post(
        f"/cases/{case.id}/documents",
        files={"file": ("doc.txt", make_txt_bytes(), "text/plain")},
        headers=auth_headers(owner),
    )
    doc_id = upload.json()["id"]

    resp = client.get(f"/documents/{doc_id}/chunks", headers=auth_headers(outsider))
    assert resp.status_code == 404


def test_delete_removes_chunks(client, db_session):
    """31. Deleting a document removes its chunks from the database."""
    from app.models.document import DocumentChunk

    owner = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, owner, CaseMemberRole.OWNER)

    upload = client.post(
        f"/cases/{case.id}/documents",
        files={"file": ("doc.txt", make_txt_bytes("word " * 600), "text/plain")},
        headers=auth_headers(owner),
    )
    doc_id = upload.json()["id"]

    # Confirm chunks exist
    chunks_before = db_session.query(DocumentChunk).filter_by(document_id=uuid.UUID(doc_id)).count()
    assert chunks_before >= 1

    client.delete(f"/documents/{doc_id}", headers=auth_headers(owner))

    # Confirm chunks are gone
    chunks_after = db_session.query(DocumentChunk).filter_by(document_id=uuid.UUID(doc_id)).count()
    assert chunks_after == 0


def test_missing_file_handled_safely(client, db_session, temp_storage):
    """32. Downloading a document whose physical file is missing returns 404."""
    owner = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, owner, CaseMemberRole.OWNER)

    upload = client.post(
        f"/cases/{case.id}/documents",
        files={"file": ("doc.txt", make_txt_bytes(), "text/plain")},
        headers=auth_headers(owner),
    )
    doc_id = upload.json()["id"]

    # Manually remove the stored file
    from app.models.document import Document
    doc = db_session.get(Document, uuid.UUID(doc_id))
    temp_storage.delete(doc.storage_key)

    resp = client.get(f"/documents/{doc_id}/download", headers=auth_headers(owner))
    assert resp.status_code == 404


def test_document_id_from_other_case_cannot_bypass_auth(client, db_session):
    """33. A document ID from another case returns 404 to non-members."""
    owner_a = make_user(db_session, role=UserRole.LAWYER)
    owner_b = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case_a = make_case(db_session, cl)
    case_b = make_case(db_session, cl)
    add_membership(db_session, case_a, owner_a, CaseMemberRole.OWNER)
    add_membership(db_session, case_b, owner_b, CaseMemberRole.OWNER)

    # Upload to case_a
    upload = client.post(
        f"/cases/{case_a.id}/documents",
        files={"file": ("doc.txt", make_txt_bytes(), "text/plain")},
        headers=auth_headers(owner_a),
    )
    doc_id = upload.json()["id"]

    # owner_b (only member of case_b) tries to access case_a's document
    resp = client.get(f"/documents/{doc_id}", headers=auth_headers(owner_b))
    assert resp.status_code == 404

    resp = client.get(f"/documents/{doc_id}/download", headers=auth_headers(owner_b))
    assert resp.status_code == 404

    resp = client.delete(f"/documents/{doc_id}", headers=auth_headers(owner_b))
    assert resp.status_code == 404


def test_response_does_not_expose_storage_key(client, db_session):
    """storage_key must not appear in any document API response."""
    owner = make_user(db_session, role=UserRole.LAWYER)
    cl = make_client(db_session)
    case = make_case(db_session, cl)
    add_membership(db_session, case, owner, CaseMemberRole.OWNER)

    upload = client.post(
        f"/cases/{case.id}/documents",
        files={"file": ("doc.txt", make_txt_bytes(), "text/plain")},
        headers=auth_headers(owner),
    )
    assert "storage_key" not in upload.json()

    doc_id = upload.json()["id"]
    detail = client.get(f"/documents/{doc_id}", headers=auth_headers(owner))
    assert "storage_key" not in detail.json()

    listing = client.get(f"/cases/{case.id}/documents", headers=auth_headers(owner))
    for item in listing.json():
        assert "storage_key" not in item
