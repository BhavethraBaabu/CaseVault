"""
Text chunking service.

Divides extracted text into overlapping chunks for future embedding and search.

Token count approximation:
    token_count = round(word_count * 1.3)

    Average English word ≈ 0.75 tokens (inverse: 1 token ≈ 0.77 words).
    This is a rough heuristic; actual token counts depend on the tokenizer
    used by the embedding model. Do NOT rely on these counts for billing
    or hard token-window limits.

Chunk parameters:
    chunk_size_words:   target number of words per chunk (default 500 ≈ 650 tokens)
    chunk_overlap_words: overlap between consecutive chunks (default 60 ≈ 78 tokens)

    chunk_size_words must be greater than chunk_overlap_words (enforced).

Page metadata:
    Each chunk records page_number = the first page from which its words came.
    This is an approximation for chunks that span page boundaries.

Determinism:
    Given the same input text, parameters, and page list, this function
    always produces the same chunk sequence.
"""

from dataclasses import dataclass

from app.services.extraction import ExtractedPage


@dataclass
class ChunkResult:
    """A single text chunk with metadata."""

    chunk_index: int
    content: str
    # Estimated token count: len(content.split()) * 1.3, rounded
    token_count: int
    # First page from which this chunk's words came; None for non-PDF docs
    page_number: int | None


def chunk_pages(
    pages: list[ExtractedPage],
    chunk_size_words: int = 500,
    chunk_overlap_words: int = 60,
) -> list[ChunkResult]:
    """
    Chunk a list of extracted pages into overlapping word-based chunks.

    Args:
        pages:               Extracted pages from ExtractionResult.
        chunk_size_words:    Target words per chunk.
        chunk_overlap_words: Words of overlap between consecutive chunks.

    Returns:
        Ordered list of ChunkResult. Empty if all pages are empty.

    Raises:
        ValueError if chunk_size_words <= chunk_overlap_words.

    Algorithm:
        1. Flatten all page text into a list of (page_number, word) pairs.
        2. Slide a window of chunk_size_words with step = chunk_size_words - overlap.
        3. For each window, join words and record the first page_number.
    """
    if chunk_size_words <= chunk_overlap_words:
        raise ValueError(
            f"chunk_size_words ({chunk_size_words}) must be greater than "
            f"chunk_overlap_words ({chunk_overlap_words})."
        )

    # Determine if page metadata should be tracked.
    # For single-page documents (DOCX/TXT) with page_number=1, still record it.
    track_pages = len(pages) > 0

    # Flatten to list of (page_number | None, word)
    words_with_pages: list[tuple[int | None, str]] = []
    for page in pages:
        page_num = page.page_number if track_pages else None
        for word in page.text.split():
            if word:  # Skip empty tokens from consecutive whitespace
                words_with_pages.append((page_num, word))

    if not words_with_pages:
        return []

    step = chunk_size_words - chunk_overlap_words
    total = len(words_with_pages)
    chunks: list[ChunkResult] = []
    chunk_index = 0
    start = 0

    while start < total:
        end = min(start + chunk_size_words, total)
        window = words_with_pages[start:end]

        content = " ".join(word for _, word in window)
        if content.strip():
            # Use the first non-None page_number in the window
            page_number = next((p for p, _ in window if p is not None), None)
            word_count = len(window)
            token_count = round(word_count * 1.3)

            chunks.append(
                ChunkResult(
                    chunk_index=chunk_index,
                    content=content,
                    token_count=token_count,
                    page_number=page_number,
                )
            )
            chunk_index += 1

        if end >= total:
            break

        start += step
        # Safety guard: guarantee forward progress even if step is misconfigured
        if start <= end - chunk_size_words:
            start = end - chunk_size_words + 1

    return chunks
