"""
File validation service.

Performs validation before any file is stored or processed:
  1. Extension whitelist
  2. Size limit
  3. Empty file rejection
  4. Content-based MIME verification (magic bytes) — does not trust
     the browser-supplied Content-Type alone.

Supported formats: PDF, DOCX, TXT
"""

import os

from app.core.config import settings

# ---------------------------------------------------------------------------
# Allowed types
# ---------------------------------------------------------------------------

ALLOWED_EXTENSIONS: frozenset[str] = frozenset({".pdf", ".docx", ".txt"})

# Map from allowed extension to validated MIME type
EXTENSION_TO_MIME: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
}

# Magic byte signatures for content-based validation
_PDF_MAGIC = b"%PDF"
_DOCX_MAGIC = b"PK\x03\x04"  # DOCX/XLSX/PPTX are ZIP archives


class FileValidationError(ValueError):
    """Raised when a file fails validation. Message is safe to return to clients."""


def validate_file(
    filename: str,
    content: bytes,
    max_size: int | None = None,
) -> str:
    """
    Validate filename and file content.

    Returns the validated MIME type string.
    Raises FileValidationError for any violation.

    Args:
        filename: The original filename (used for extension check only).
        content:  Raw file bytes.
        max_size: Maximum allowed size in bytes; defaults to settings value.

    Security notes:
        - Extension is used for type determination only; never as a filesystem path.
        - Content is inspected via magic bytes, independent of browser MIME claim.
        - TXT is validated by attempting UTF-8 decode.
    """
    if max_size is None:
        max_size = settings.max_upload_size_bytes

    # 1. Extension
    _, ext = os.path.splitext(filename.lower())
    if ext not in ALLOWED_EXTENSIONS:
        raise FileValidationError(
            f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )

    # 2. Empty content
    if not content:
        raise FileValidationError("File is empty.")

    # 3. Size
    if len(content) > max_size:
        limit_mb = max_size / (1024 * 1024)
        raise FileValidationError(
            f"File size {len(content):,} bytes exceeds the {limit_mb:.0f} MB limit."
        )

    # 4. Content-based MIME verification
    mime = _verify_content(ext, content)
    return mime


def _verify_content(ext: str, content: bytes) -> str:
    """
    Verify file content matches the expected format for the given extension.

    Returns the canonical MIME type.
    Raises FileValidationError if the content does not match the extension.
    """
    if ext == ".pdf":
        if not content.startswith(_PDF_MAGIC):
            raise FileValidationError(
                "File does not appear to be a valid PDF (missing PDF header)."
            )
        return EXTENSION_TO_MIME[".pdf"]

    if ext == ".docx":
        if not content.startswith(_DOCX_MAGIC):
            raise FileValidationError(
                "File does not appear to be a valid DOCX (missing ZIP/DOCX header)."
            )
        return EXTENSION_TO_MIME[".docx"]

    if ext == ".txt":
        try:
            content.decode("utf-8")
        except UnicodeDecodeError:
            raise FileValidationError(
                "TXT file is not valid UTF-8 encoded text."
            )
        return EXTENSION_TO_MIME[".txt"]

    # Should not reach here given extension whitelist above
    raise FileValidationError(f"Unsupported extension: {ext!r}")


def sanitize_filename(filename: str) -> str:
    """
    Return a safe display filename.

    Strips path components (basename only) and replaces characters that
    could cause issues in Content-Disposition headers or logs.
    The result is used for display only — never as a filesystem path.
    """
    import re

    # Basename only — removes any directory traversal component
    name = os.path.basename(filename)
    # Replace characters outside safe set with underscore
    name = re.sub(r'[^\w.\-]', "_", name)
    # Collapse multiple underscores
    name = re.sub(r"_+", "_", name)
    # Limit length
    name = name[:255]
    return name or "unnamed_file"
