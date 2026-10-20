# CaseVault — Interview Architecture Notes

This document covers the design decisions, trade-offs, and honest limitations of the
CaseVault implementation. Everything here reflects the actual code — nothing is aspirational.

---

## Technology Choices

### Why FastAPI?

- **Async-first**: Starlette foundation handles concurrent requests without threads for I/O-bound
  work (LLM API calls, DB queries).
- **Pydantic at every boundary**: All request/response shapes are validated at entry points.
  Type errors fail fast before reaching business logic.
- **Dependency injection**: FastAPI's `Depends()` system makes `get_current_user()`,
  `get_authorized_case()`, and `get_db()` composable and independently testable.
- **Python ecosystem fit**: same language as the ML/AI libraries (sentence-transformers,
  SQLAlchemy, LLM SDKs), no polyglot boundary.

### Why Next.js (App Router)?

- **Pure client boundary**: No backend logic in Next.js. All auth, authorization, and data
  access live in FastAPI. Avoids split security surfaces.
- **TypeScript throughout**: Shared type safety between React components and the API client.
- **Route guards are UX only**: redirects to `/login` are client-side conveniences.
  The backend enforces authorization on every request independently.

### Why PostgreSQL + pgvector?

- **Native vector column**: `vector(384)` type with HNSW indexing for approximate
  nearest-neighbor search in sub-linear time.
- **Row-level isolation via SQL**: authorization is encoded in the same query that does
  semantic retrieval. Unauthorized rows never appear in results at any position.
- **Single data store**: case metadata, documents, chunks, embeddings, conversations,
  timeline events, and contradictions all live in one transactional database. No
  consistency gap between relational data and a separate vector store.

---

## How Permission Enforcement Before Retrieval Works

This is the most important security invariant in the system.

### The wrong approach (never used here)

```python
chunks = db.query(DocumentChunk).all()      # loads all chunks
return [c for c in chunks if user_has_access(c)]  # filters afterward
```

This loads unauthorized data into application memory. A filter bug leaks data.

### The correct approach (used everywhere)

```python
chunks = (
    db.query(DocumentChunk)
    .join(Document, Document.id == DocumentChunk.document_id)
    .join(Case, Case.id == Document.case_id)
    .join(CaseMembership, CaseMembership.case_id == Case.id)
    .filter(CaseMembership.user_id == current_user.id)
    .order_by(distance)
    .limit(k)
    .all()
)
```

Authorization is part of the SQL WHERE clause. The database engine never returns
unauthorized rows — not even in discarded positions before `LIMIT k`.

This pattern is applied consistently across:
- Case listing (`list_cases_for_user`)
- Document listing and download
- Semantic search (`semantic_search`)
- RAG context retrieval (`ask`)
- Agent tool calls (`search_documents`, `get_document_context`)
- Timeline document access (`_get_authorized_documents`)

---

## Authentication Design

1. Passwords hashed with bcrypt (direct, no passlib — passlib has a breaking incompatibility
   with bcrypt 5.x).
2. Login issues a signed HS256 JWT containing `sub` (user UUID), `role` (informational), `exp`.
3. On every request, `get_current_user()`:
   - Decodes and verifies JWT signature and expiry
   - Loads user from database by UUID
   - Checks `is_active` flag
4. **JWT `role` claim is never authoritative.** Role is always re-read from the database.
   This prevents a user whose role was downgraded from using an old token to retain elevated access.

---

## Embedding, Chunking, and Retrieval Flow

### Chunking

Word-based sliding window: 500-word chunks, 60-word overlap. Token estimate: `words × 1.3`.
Overlap preserves context across boundaries, improving recall for queries that span chunks.

### Embedding

`sentence-transformers/all-MiniLM-L6-v2`: 384-dim, runs on CPU, ~90 MB download.
Deterministic (same text → same vector). No API key required.

`EmbeddingVector` TypeDecorator handles `vector(384)` in PostgreSQL and JSON TEXT in SQLite,
allowing the same ORM model to work in both environments.

### Retrieval

```sql
SELECT chunks.*, 1 - (embedding <=> :query_vector) AS similarity
FROM document_chunks chunks
JOIN documents ON documents.id = chunks.document_id
JOIN cases ON cases.id = documents.case_id
JOIN case_memberships ON case_memberships.case_id = cases.id
WHERE case_memberships.user_id = :current_user_id
  AND chunks.embedding_status = 'READY'
ORDER BY embedding <=> :query_vector
LIMIT :k
```

Authorization is in the WHERE clause — before `ORDER BY distance LIMIT k`.

---

## RAG: Citation Grounding and Hallucination Risks

### Citation construction

Retrieved chunks are numbered sequentially in the prompt:
```
[SOURCE:1]
Document: contract.pdf | Case: Acme v. Widgets | Page: 3
---
Payment is due within 30 days...
---
```

The system prompt instructs: "Cite each claim as [SOURCE:N]. If there is insufficient
evidence, respond only with INSUFFICIENT_EVIDENCE."

### Citation validation (server-side)

After the LLM responds, `_parse_and_validate_citations()`:
1. Extracts all `[SOURCE:N]` references with a regex
2. Validates each N against the retrieved chunk list (0-indexed, range check)
3. Silently discards fabricated or out-of-range IDs
4. Maps valid IDs → `SourceCitation` objects

The client only receives citations that correspond to actual retrieved, authorized chunks.
Even `[SOURCE:99]` from a hallucinating LLM is silently dropped.

### Remaining hallucination risks

- The LLM answer text itself may contain hallucinated facts not from any source.
  Citation validation only validates the index references, not the claims.
- Prompt injection from crafted documents can influence the LLM's answer content.
  The server validates citations and authorization regardless, but cannot fix misleading text.

---

## Agent Tool Validation

### Allowlist enforcement

```python
ALLOWED_TOOL_NAMES: frozenset[str] = frozenset({
    "search_documents",
    "list_cases",
    "get_case_details",
    "get_document_context",
})
```

Unknown tool names are rejected before execution. The LLM cannot invent tools, call OS
commands, or access the filesystem.

### JSON-in-prompt vs. OpenAI function calling

The agent uses JSON-in-prompt structured output:
```json
{"type": "tool_call", "tool": "search_documents", "args": {...}}
{"type": "answer", "content": "..."}
```

**Why not OpenAI function calling:**
- Works with any `LLMProvider` implementation — not coupled to OpenAI's API.
- Fully testable with `FakeSequentialProvider` (no network calls).
- Trade-off: real LLMs may not always comply. Malformed JSON is treated as a final answer.

### Identity security

The user identity comes from the JWT on the `/agent/run` request.
Even if a malicious document instructs the LLM to call a tool with a different `case_id`,
the tool independently re-checks case membership using the authenticated user's identity.

---

## AI Case Timeline and Contradiction Detector

### Pipeline

**Phase 1 — Event extraction (one LLM call per document):**
- Authorized documents fetched via `CaseMembership JOIN/WHERE`
- Up to 3 chunks / 6000 chars per document included in prompt
- LLM returns JSON array of `{title, description, event_type, event_date, source_quote, ...}`
- Each event's `source_quote` is verified as an exact substring of the chunk text
- Hallucinated quotes rejected before persistence

**Phase 2 — Contradiction detection (one LLM call for all events):**
- All extracted events with 300-char source excerpts sent in one prompt
- LLM returns JSON array of `{summary, severity, source_quote_a, source_quote_b, ...}`
- Both quotes verified in source texts
- Self-contradictions (same chunk vs. itself) are excluded

### Why exact-match quote verification?

The LLM is instructed to copy quotes verbatim. Exact-match is conservative:
minor paraphrasing causes rejection, but it guarantees that every stored quote
is provably from the source document. The alternative — fuzzy matching — would
require defining a similarity threshold and introduces false positives.

### Uncertainty disclosure

- `ai_generated=True` on every API response object
- `extraction_confidence` and `confidence` fields surfaced (model-estimated, not calibrated)
- UNREVIEWED → REVIEWED | DISPUTED review workflow for human oversight
- Frontend shows a persistent AI disclaimer banner
- Analysis response message explicitly states "All results require human review"

---

## Document Security

### Storage

Files stored at `{case_id}/{uuid4}` — storage key never derived from filename.
UUID-based keys prevent enumeration and path-predictability attacks.

### Path-traversal prevention

`_safe_path()` in `LocalStorage`:
```python
resolved = (self.base_dir / key).resolve()
if not str(resolved).startswith(str(self.base_dir)):
    raise StorageError("Path traversal attempt")
```

Resolves symlinks and validates the final path is inside `base_dir` before any I/O.

### `storage_key` not in API responses

The internal storage path is excluded from all Pydantic response schemas.
Clients never see the filesystem path.

---

## Observability and Request IDs

### ContextVar-based request ID

Every request gets a unique ID stored in `ContextVar[str]` (thread/async-safe).
The ID propagates to all log lines within the request without explicit parameter passing.
After the response, the ContextVar is reset via `token` to prevent ID leakage.

```
2026-10-14T12:00:00 INFO  casevault [req-abc123] app.services.rag - rag.ask completed
duration_ms=342 llm_ms=280 chunks_retrieved=5 citations_validated=2
```

### What is never logged

- Passwords, JWTs, API keys
- Document text or extracted chunks
- LLM prompts and responses
- User question text
- Internal file paths

### Liveness vs. readiness

- `/health/live`: always 200. Answers "is the process alive?"
- `/health/ready`: 200 or 503. DB check runs in a `ThreadPoolExecutor` with a timeout.
  Prevents a hung DB connection from blocking the probe indefinitely.
  Kubernetes `readinessProbe` removes the pod from the load balancer if this returns 503.

---

## Current Limitations and Production Hardening

| Gap | Status | Production fix |
|---|---|---|
| Real LLM not tested in CI | All tests use fake providers | Integration tests against real OpenAI API (separate CI job) |
| PostgreSQL not live-tested | SQLite in-memory only | Docker-based CI with `pgvector/pgvector:pg17` |
| JWT revocation | Logout is client-side | Redis revocation list keyed by `jti` + short-lived tokens |
| Rate limiting | Not implemented | nginx `limit_req` or API Gateway on `/auth/login` |
| Synchronous extraction | Blocks HTTP thread | Celery + Redis background job queue |
| Synchronous timeline analysis | Blocks HTTP thread | Same background queue |
| Local filesystem storage | Cannot scale horizontally | Object storage (S3/GCS) via same `Storage` interface |
| No streaming | LLM responses block | Server-Sent Events for chat streaming |
| Prompt injection | Cannot be fully prevented | Defence-in-depth: citation validation, authorization, quote verification |
| Scanned PDFs | Rejected (no OCR) | Tesseract integration as post-processor |
| TLS | Not in this repo | Terminate at load balancer / reverse proxy |
| Audit trail | Not implemented | Append-only access log per resource for compliance (HIPAA, SOC 2) |

---

## Trade-offs Worth Discussing

| Decision | Why | Trade-off |
|---|---|---|
| Authorization before retrieval (SQL JOIN) | Never load unauthorized data | Slightly more complex queries; cannot be bypassed |
| Resource-hiding (404 not 403) | Prevent resource enumeration | Harder to debug authorization issues in development |
| Role re-read from DB each request | Prevents token-based role escalation | One extra DB query per request |
| JSON-in-prompt tool calling | Provider-agnostic, fully testable | Real LLMs may not always comply with JSON format |
| Citation validation server-side | LLM cannot fabricate authorized sources | LLM answer text itself can still hallucinate |
| Exact-match quote verification | Zero false positives on source grounding | Rejects minor paraphrasing; LLM must copy verbatim |
| EmbeddingVector TypeDecorator | Single ORM model for PG + SQLite | Tests validate authorization, not pgvector operators |
| `ContextVar` for request ID | Thread/async-safe; no explicit passing | Must reset via token to prevent leakage |
| Local embedding model | No API key, deterministic, free | ~90 MB download; ~200–350 MB RAM on CPU |
| Single PostgreSQL store | Transactional consistency across all data | Cannot use a managed vector DB with separate consistency |
