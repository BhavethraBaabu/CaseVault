"""
Local filesystem storage abstraction.

Provides a small interface so object storage (S3, GCS) can be added later
without modifying document processing logic.

Security invariants:
  - storage_key is always a server-generated UUID-based path.
  - _safe_path() resolves and validates that the target is within base_dir,
    preventing path-traversal attacks.
  - Never accept user-supplied strings as storage keys.
  - Absolute server paths are never returned to API callers.
"""

import os
from pathlib import Path


class StorageError(Exception):
    """Raised for storage I/O failures."""


class LocalStorage:
    """
    Store files in a local directory tree.

    Not intended for production scale; replace with an object-storage
    backend (e.g. S3) for production deployments.

    Limitation: binary file content is loaded entirely into memory on
    reads. This is acceptable for the configured 10 MB upload limit in
    development, but should be replaced with streaming for production.
    """

    def __init__(self, base_dir: str) -> None:
        self.base_dir = Path(base_dir).resolve()

    def save(self, key: str, data: bytes) -> None:
        """Write data to storage at the given key. Creates parent dirs."""
        path = self._safe_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def load(self, key: str) -> bytes:
        """Read and return data stored at key. Raises StorageError if missing."""
        path = self._safe_path(key)
        if not path.exists():
            raise StorageError(f"Storage key not found: {key}")
        return path.read_bytes()

    def delete(self, key: str) -> None:
        """Delete the file at key. No-op if it does not exist."""
        path = self._safe_path(key)
        if path.exists():
            path.unlink()

    def exists(self, key: str) -> bool:
        """Return True if a file exists at key."""
        return self._safe_path(key).exists()

    def _safe_path(self, key: str) -> Path:
        """
        Resolve key to an absolute path inside base_dir.

        Raises ValueError for any key that would escape base_dir,
        preventing path-traversal attacks.

        Explicitly rejects:
        - Absolute paths (starting with "/" or os.sep)
        - Keys containing backslashes (not valid in storage keys; blocks
          Windows-style traversal attempts on Unix where "\\" is otherwise
          a valid filename character)
        - Any resolved path outside base_dir (handles ".." after join)
        """
        # Reject absolute paths — valid storage keys are always relative
        if key.startswith("/") or (os.sep != "/" and key.startswith(os.sep)):
            raise ValueError(f"Invalid storage key (potential path traversal): {key!r}")
        # Reject backslashes — valid storage keys never contain them
        if "\\" in key:
            raise ValueError(f"Invalid storage key (potential path traversal): {key!r}")
        candidate = (self.base_dir / key).resolve()
        inside = str(candidate).startswith(str(self.base_dir) + os.sep)
        if not inside and candidate != self.base_dir:
            raise ValueError(f"Invalid storage key (potential path traversal): {key!r}")
        return candidate


# ---------------------------------------------------------------------------
# Module-level singleton — override in tests via set_storage()
# ---------------------------------------------------------------------------

_storage: LocalStorage | None = None


def get_storage() -> LocalStorage:
    """Return the active storage instance, initializing from config if needed."""
    global _storage
    if _storage is None:
        from app.core.config import settings

        _storage = LocalStorage(settings.document_storage_path)
    return _storage


def set_storage(storage: LocalStorage) -> None:
    """
    Override the active storage instance.

    Used in tests to redirect file I/O to a temporary directory.
    Call with None to reset to the default (config-based) instance.
    """
    global _storage
    _storage = storage
