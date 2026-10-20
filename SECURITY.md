# CaseVault — Security Documentation

This document describes the threat model, security controls, known limitations,
and environment configuration for CaseVault.  It is updated as each milestone
adds or changes security-relevant behaviour.

---

## Threat Model

### Assets protected

| Asset | Sensitivity |
|---|---|
| Legal case documents and extracted text | High — confidential client data |
| Case metadata (parties, status, description) | High |
| User credentials (passwords, JWTs) | High |
| API keys for external LLM/embedding providers | High |
| User identity and role assignments | Medium |
| Conversation history | Medium |
| Application configuration | Medium |

### Trust boundaries

```
Internet / Browser
       │  HTTPS (TLS terminates at load balancer — not in this repo)
       ▼
  FastAPI (backend)  ──────  PostgreSQL + pgvector
       │                              │
       │  SQL queries only            │  Row-level isolation via JOIN/WHERE
       ▼                              ▼
  LLM provider (OpenAI API)     Local filesystem storage
  Embedding model (local)        (UUID-keyed, path-traversal-guarded)
```

**Untrusted inputs:**
- All HTTP request data (headers, body, file uploads)
- All document content (after upload)
- All LLM-generated text (tool calls, answers, citations)

**Trusted within the backend:**
- SQLAlchemy ORM (parameterized queries, no raw SQL with user data)
- JWT claims validated and looked up in the database on every request
- Pydantic schemas at every API boundary

### Principal threat actors

1. **Unauthenticated attacker** — No valid JWT.  Can only reach public endpoints
   (`/health`, `/auth/login`, `/auth/register`).  All other endpoints return
   401/403 before touching the database.

2. **Authenticated but unauthorized user** — Valid JWT, but no membership in a
   specific case.  Cannot see case/document metadata (HTTP 404 resource-hiding).
   Cannot retrieve document chunks through any tool.

3. **Compromised account** — A user whose credentials have been stolen.
   Blast radius limited to their own case memberships.  Cannot elevate to ADMIN
   via API (role is set by ADMIN users only).

4. **Malicious document** — A PDF/DOCX/TXT uploaded by an authorized user that
   contains crafted content intended to:
   - Inject instructions into the LLM ("prompt injection")
   - Exhaust extraction resources (large/complex document)
   - Exploit PDF/DOCX parser vulnerabilities

5. **Resource exhaustion** — Large or rapid requests intended to exhaust memory,
   CPU, or LLM API quota.

6. **Compromised LLM output** — The language model produces tool calls that
   reference unauthorized cases, fabricated citations, or attempt to call
   unregistered tools.

---

## Implemented Security Controls

### Authentication

| Control | Implementation | File |
|---|---|---|
| Password hashing | bcrypt (no passlib) | `core/security.py` |
| JWT signing | HS256 with SECRET_KEY | `core/security.py` |
| JWT expiration | 30 min default (configurable) | `core/config.py` |
| Role re-read from DB | JWT role claim is informational only | `api/deps.py` |
| Inactive user check | HTTP 403 before any resource access | `api/deps.py` |

### Authorization

| Control | Implementation | File |
|---|---|---|
| Resource-hiding (404 not 403) | Non-members see 404 for cases/documents | `api/deps.py` |
| Pre-query authorization | JOIN/WHERE before ORDER BY LIMIT | `api/deps.py`, `services/search.py` |
| Per-tool authorization | Every tool call re-checks membership | `services/agent_tools.py` |
| Case-document binding | document.case_id must match supplied case_id | `services/agent_tools.py` |
| Role enforcement | ADMIN bypasses membership; others need CaseMembership | `api/deps.py` |

### AI Agent

| Control | Implementation | File |
|---|---|---|
| Tool allowlist | Unknown tool names rejected before execution | `services/agent.py` |
| Argument validation | Pydantic schemas per tool (strict types, range limits) | `services/agent_tools.py` |
| Max tool calls | `agent_max_tool_calls` (default 5) | `core/config.py` |
| Max iterations | `agent_max_iterations` (default 6) | `core/config.py` |
| Max task length | `agent_max_task_length` (default 2000 chars) | `core/config.py` |
| Tool output truncation | `agent_max_tool_output_chars` (default 4000) | `services/agent.py` |
| Server-side identity | User always from JWT; LLM cannot supply/override | `api/v1/agent.py` |
| Read-only tools | No tools create, modify, or delete data | `services/agent_tools.py` |

### Prompt Injection Defence

| Control | Status | Notes |
|---|---|---|
| Evidence delimited in prompt | Implemented | `[SOURCE:N]` blocks with `---` separators |
| System instruction separation | Implemented | Policy text is never in the evidence block |
| "Treat content as data" instruction | Implemented | Agent and RAG system prompts |
| Tool allowlist (backend) | Implemented | Even if LLM "falls for" injection, backend rejects |
| Per-call authorization (backend) | Implemented | Even if LLM calls with wrong case_id, backend rejects |
| Citation validation | Implemented | Fabricated `[SOURCE:N]` indices silently discarded |
| **Complete prevention** | **Not possible** | Prompt injection cannot be fully eliminated. A sufficiently crafted document and an adversarial LLM response can influence output. The backend layers above are defence-in-depth, not elimination. |

### Document Ingestion

| Control | Implementation | File |
|---|---|---|
| Extension whitelist | `.pdf`, `.docx`, `.txt` only | `services/file_validation.py` |
| Magic-byte verification | PDF: `%PDF`, DOCX: `PK\x03\x04`, TXT: UTF-8 | `services/file_validation.py` |
| Size limit | `max_upload_size_bytes` (default 10 MB) | `core/config.py` |
| Empty file rejection | Explicit empty-content check | `services/file_validation.py` |
| Filename sanitization | Basename only; `[a-zA-Z0-9_.\-]` charset; 255-char limit | `services/file_validation.py` |
| UUID-based storage keys | `{case_id}/{uuid4}` — never derived from filename | `services/document.py` |
| Path-traversal guard | `_safe_path()` resolves and validates inside base_dir | `services/storage.py` |
| No storage paths in API | `storage_key` excluded from all response schemas | `schemas/document.py` |

### AI Case Timeline and Contradiction Detector

| Control | Implementation | File |
|---|---|---|
| Authorization before document access | `_get_authorized_documents()` uses CaseMembership JOIN/WHERE | `services/timeline.py` |
| Source-quote verification | Every `source_quote` verified as exact substring of chunk text | `services/timeline.py` |
| Hallucinated quotes rejected | Quotes not found in source text are silently discarded, never persisted | `services/timeline.py` |
| OWNER/MEMBER gate on analysis | `require_case_role(OWNER, MEMBER)` on POST analyze and PATCH review | `api/v1/timeline.py` |
| Cross-case access prevention | `case_id` always in WHERE clause for event/contradiction queries | `services/timeline.py` |
| Max documents bound | `max_documents` (1–10) limits LLM calls and prompt exposure per request | `services/timeline.py` |
| AI uncertainty labelled | `ai_generated=True` on all response objects; disclaimer in frontend | `api/v1/timeline.py` |
| No full document text in logs | Source chunks are passed to LLM but never written to logs | `services/timeline.py` |
| Single-case document scope | Documents from other cases structurally cannot enter the prompt | `services/timeline.py` |

### HTTP / API Hardening (Day 8)

| Control | Implementation | File |
|---|---|---|
| Request body size limit | `_BodySizeLimitMiddleware` checks Content-Length | `main.py` |
| Security response headers | `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` | `main.py` |
| Configurable CORS | `CORS_ORIGINS` env var (comma-separated) | `core/config.py` |
| Conditional API docs | `DOCS_ENABLED=false` disables `/docs` and `/redoc` | `core/config.py`, `main.py` |
| Startup secret-key warning | Logs CRITICAL if `SECRET_KEY` matches known defaults | `main.py` |
| No stack traces in errors | All generic exceptions caught, generic message returned | `api/v1/*.py` |

---

## Environment Variables

### Required in production

| Variable | Description |
|---|---|
| `SECRET_KEY` | Random 32-byte hex string. Generate: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `DATABASE_URL` | PostgreSQL connection string |
| `LLM_API_KEY` | API key for the configured LLM provider |

### Recommended in production

| Variable | Default | Recommended value |
|---|---|---|
| `DOCS_ENABLED` | `true` | `false` — disables `/docs` and `/redoc` |
| `CORS_ORIGINS` | `http://localhost:3000` | Your actual frontend domain(s) |
| `MAX_UPLOAD_SIZE_BYTES` | `10485760` (10 MB) | Tune to your document sizes |
| `DEBUG` | `false` | Keep `false` in production |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Lower (e.g. 15) for higher security |

### Configurable limits (agent)

| Variable | Default | Effect |
|---|---|---|
| `AGENT_MAX_TOOL_CALLS` | `5` | Maximum tool invocations per agent run |
| `AGENT_MAX_ITERATIONS` | `6` | Maximum LLM round-trips per agent run |
| `AGENT_MAX_TASK_LENGTH` | `2000` | Maximum characters in an agent task |
| `AGENT_MAX_TOOL_OUTPUT_CHARS` | `4000` | Maximum tool result size in LLM context |

---

## Sandbox Design

CaseVault does **not** execute arbitrary user-supplied code.  All four agent
tools are read-only database and storage queries:

- `search_documents` — SQL query + Python cosine similarity
- `list_cases` — SQL query
- `get_case_details` — SQL query
- `get_document_context` — SQL query

There is no shell access, no arbitrary file read/write, no `eval()`, and no
user-controlled import in any tool.

The FastAPI process itself runs in Docker (`infra/docker-compose.yml`) but the
container is not hardened for untrusted code execution.  If a code-execution
feature is added in the future, it must run in a separate container with:
- A minimal non-root image
- Read-only root filesystem
- Dropped Linux capabilities (`--cap-drop=ALL`)
- No Docker socket mount
- No host mounts
- Restricted network access
- CPU, memory, and process limits (`--cpus`, `--memory`, `--pids-limit`)
- Hard execution time limits

---

## Known Limitations

1. **Prompt injection cannot be fully prevented.**  The backend enforces
   authorization regardless of LLM output, but a crafted document can still
   influence the LLM's answer or cause it to call legitimate tools with
   unexpected (authorized) arguments.

2. **Chunked transfer-encoding bypasses the body size middleware.**  Requests
   without a `Content-Length` header are not blocked at the middleware level.
   The file-size check inside `validate_file()` is the backstop for uploads.

3. **Document extraction is synchronous.**  Uploading a near-limit document
   blocks the worker thread during extraction.  Resource exhaustion via many
   concurrent large uploads is possible without a rate limiter or background
   queue.

4. **No rate limiting.**  There is no request rate limiter in this codebase.
   Deploy behind a reverse proxy (nginx, Caddy, AWS ALB) that enforces per-IP
   rate limits, especially on `/auth/login`.

5. **TLS not in this repo.**  Terminate TLS at the load balancer or reverse
   proxy.  Do not run bare HTTP in production.

6. **Default Postgres password.**  `docker-compose.yml` defaults
   `POSTGRES_PASSWORD=casevault`.  Override with a strong password in
   production.

7. **LLM responses not verified against a live model.**  All agent and RAG
   tests use deterministic fake providers.  Actual compliance of the real LLM
   with system prompt instructions is not tested here.

8. **Embedding model downloaded at runtime.**  The first request after deployment
   may be slow (~90 MB download).  This is not a security concern but is a
   reliability concern for cold starts.

---

## Running Security Tests

```bash
# All backend tests (includes security hardening suite)
cd backend
source .venv/bin/activate
python -m pytest tests/ -v

# Security hardening tests only
python -m pytest tests/test_security_hardening.py -v

# Timeline security tests
python -m pytest tests/test_timeline.py -v

# Static analysis
python -m ruff check .

# Frontend type checks
cd ../frontend
npx tsc --noEmit

# Frontend lint
npm run lint
```

---

## Docker Configuration Notes

The `infra/docker-compose.yml` is intended for **development and evaluation
only**.  For production:

1. Set `SECRET_KEY` to a strong random value (not the default).
2. Set `POSTGRES_PASSWORD` to a strong password.
3. Remove the `../backend:/app` volume mount (it exposes source code).
4. Set `DOCS_ENABLED=false` to disable the API explorer.
5. Add resource limits (`mem_limit`, `cpus`) to each service.
6. Run behind a reverse proxy with TLS and rate limiting.
7. Do not expose port 5432 (PostgreSQL) to the internet.
