"""
Text extraction and normalization service.

Extracts plain text from supported document formats:
  - PDF:  uses pypdf. Text-based PDFs only. Scanned/image PDFs produce
          empty extraction — handled gracefully (status→FAILED).
          OCR is NOT supported and is NOT silently claimed.
  - DOCX: uses python-docx. Extracts paragraph and table cell text.
  - TXT:  UTF-8 decode with fallback error handling.

Each format returns a list of (page_number, text) pairs.
Page numbers are 1-indexed for PDFs; always (1, full_text) for DOCX/TXT.

Normalization:
  - Normalize line endings to '\n'.
  - Collapse runs of more than two consecutive newlines.
  - Strip leading/trailing whitespace per line.
  - Preserve single blank lines (paragraph boundaries).
  - Avoid aggressive transformations that change legal text meaning.
"""

import io
from dataclasses import dataclass


@dataclass
class ExtractedPage:
    """Text content from a single page (or whole document for non-PDF)."""

    page_number: int  # 1-indexed
    text: str


@dataclass
class ExtractionResult:
    """Result of extracting text from a document."""

    pages: list[ExtractedPage]
    page_count: int


class ExtractionError(Exception):
    """Raised when text extraction fails. Message is safe to return to clients."""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def extract_text(content: bytes, content_type: str) -> ExtractionResult:
    """
    Extract text from document bytes.

    Args:
        content:      Raw file bytes.
        content_type: Validated MIME type string.

    Returns:
        ExtractionResult with pages and page_count.

    Raises:
        ExtractionError if extraction cannot produce usable text.
    """
    if content_type == "application/pdf":
        return _extract_pdf(content)
    if content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return _extract_docx(content)
    if content_type == "text/plain":
        return _extract_txt(content)
    raise ExtractionError(f"Unsupported content type for extraction: {content_type!r}")


# ---------------------------------------------------------------------------
# Format-specific extractors
# ---------------------------------------------------------------------------


def _extract_pdf(content: bytes) -> ExtractionResult:
    """
    Extract text from a PDF using pypdf.

    Limitation: text-based PDFs only. Scanned/image PDFs will yield empty
    text and result in a FAILED document status.
    OCR is NOT performed.
    """
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ExtractionError("pypdf is not installed.") from exc

    try:
        reader = PdfReader(io.BytesIO(content))
    except Exception:
        raise ExtractionError("Could not read PDF — file may be corrupted or password-protected.")

    pages: list[ExtractedPage] = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            raw = page.extract_text() or ""
        except Exception:
            raw = ""
        normalized = _normalize(raw)
        if normalized:
            pages.append(ExtractedPage(page_number=i, text=normalized))

    if not pages:
        raise ExtractionError(
            "No extractable text found. The PDF may be scanned or image-based. "
            "OCR is not supported."
        )

    return ExtractionResult(pages=pages, page_count=len(reader.pages))


def _extract_docx(content: bytes) -> ExtractionResult:
    """
    Extract text from a DOCX file using python-docx.

    Extracts paragraph text and table cell text in document order.
    """
    try:
        from docx import Document as DocxDocument
    except ImportError as exc:
        raise ExtractionError("python-docx is not installed.") from exc

    try:
        doc = DocxDocument(io.BytesIO(content))
    except Exception:
        raise ExtractionError("Could not read DOCX — file may be corrupted or not a valid DOCX.")

    parts: list[str] = []

    for block in doc.element.body:
        tag = block.tag.split("}")[-1] if "}" in block.tag else block.tag
        if tag == "p":
            # Paragraph
            from docx.oxml.ns import qn

            text = "".join(r.text for r in block.iter(qn("w:t")) if r.text)
            if text.strip():
                parts.append(text)
        elif tag == "tbl":
            # Table — iterate rows and cells
            from docx.oxml.ns import qn

            for row in block.iter(qn("w:tr")):
                row_texts = []
                for cell in row.iter(qn("w:tc")):
                    cell_text = "".join(r.text for r in cell.iter(qn("w:t")) if r.text)
                    if cell_text.strip():
                        row_texts.append(cell_text.strip())
                if row_texts:
                    parts.append(" | ".join(row_texts))

    full_text = "\n".join(parts)
    normalized = _normalize(full_text)

    if not normalized:
        raise ExtractionError("No extractable text found in DOCX.")

    return ExtractionResult(
        pages=[ExtractedPage(page_number=1, text=normalized)],
        page_count=1,
    )


def _extract_txt(content: bytes) -> ExtractionResult:
    """
    Decode and extract text from a UTF-8 text file.
    """
    try:
        raw = content.decode("utf-8")
    except UnicodeDecodeError:
        raise ExtractionError("TXT file is not valid UTF-8.")

    normalized = _normalize(raw)
    if not normalized:
        raise ExtractionError("TXT file contains no usable text after normalization.")

    return ExtractionResult(
        pages=[ExtractedPage(page_number=1, text=normalized)],
        page_count=1,
    )


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def _normalize(text: str) -> str:
    """
    Normalize extracted text.

    Steps:
      1. Normalize line endings to '\\n'.
      2. Strip trailing whitespace per line.
      3. Collapse runs of 3+ consecutive blank lines to 2.
      4. Strip leading/trailing whitespace from the whole text.

    Intentionally conservative: preserves single blank lines as paragraph
    boundaries and does not alter legal punctuation or word order.
    """
    import re

    # Normalize CRLF and CR to LF
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Strip trailing whitespace from each line
    lines = [line.rstrip() for line in text.split("\n")]
    text = "\n".join(lines)
    # Collapse 3+ consecutive newlines to 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
