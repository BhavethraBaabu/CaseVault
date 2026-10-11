# CaseVault — Architecture

## System Overview

```
Browser
  |
  | HTTPS
  v
Next.js Frontend (port 3000)
  |
  | REST API calls (NEXT_PUBLIC_API_URL)
  v
FastAPI Backend (port 8000)
  |
  | SQLAlchemy ORM
  v
PostgreSQL + pgvector (port 5432)
  |
  | (future)
  v
RAG / AI Services (Day 5+)
```

## Layers

### Frontend — Next.js (App Router)
- TypeScript + Tailwind CSS
- Communicates with backend **only through REST API calls**
- Never has direct database access
- Never exposes `DATABASE_URL` or server-side secrets
- Environment variable `NEXT_PUBLIC_API_URL` is the only backend reference

### Backend — FastAPI
- Python 3.13 + FastAPI + SQLAlchemy
- Owns all database access
- Owns all business logic
- Future: owns authorization before any data retrieval
- Future: owns AI/RAG pipeline

### Database — PostgreSQL + pgvector
- PostgreSQL 17 with the `vector` extension
- Accessed only by the backend
- Future: document chunk embeddings stored as `vector` columns for semantic search

### Infrastructure — Docker Compose
- `postgres` service: `pgvector/pgvector:pg17`
- `backend` service: Python FastAPI
- `frontend` service: Next.js

---

## Authentication & Authorization (Day 2)

### Request Flow

```
Browser
  |
  | HTTPS — Authorization: Bearer <JWT>
  v
Next.js Frontend
  |
  | REST — Authorization: Bearer <JWT>
  v
FastAPI Backend
  |
  +-- JWT validation (python-jose)
  |     decode token → verify signature → check expiration
  +-- User lookup (PostgreSQL)
  |     load user by ID from JWT sub claim
  +-- User active check
  |     reject inactive users with HTTP 403
  +-- Role authorization (require_role dependency)
  |     compare user.role (from DB) against required roles
  v
Database query (scoped to allowed resources)
```

### Authentication vs Authorization

| Concept | Question | Implementation |
|---|---|---|
| **Authentication** | Who are you? | JWT validation + DB user lookup |
| **Authorization** | What are you allowed to access? | `require_role()` dependency enforces roles before DB queries |

### JWT Token

Payload contains only:
- `sub` — user UUID (string)
- `role` — user role (informational; authoritative role is re-read from DB)
- `exp` — expiration timestamp

Never contains: passwords, documents, case data, or sensitive information.

### Logout Limitation

CaseVault uses stateless JWTs. The `/auth/logout` endpoint instructs the client
to discard the token but does NOT invalidate it server-side. The token remains
cryptographically valid until its `exp` claim.

**Production recommendation**: short-lived tokens (5–15 min) with refresh-token
rotation, or a token revocation list (e.g. Redis blocklist keyed by `jti`).

### Frontend vs Backend Protection

```
Frontend route guard (/login redirect) = UX convenience
Backend auth dependency (get_current_user) = SECURITY
```

The backend enforces authentication independently on every request.
Frontend route protection can always be bypassed by a determined user.

### User Roles

| Role | Access |
|---|---|
| `ADMIN` | Full system access |
| `LAWYER` | Normal authenticated access |
| `RESTRICTED_LAWYER` | Authenticated but intentionally limited scope (Day 3+) |

Roles are stored in PostgreSQL. The JWT `role` claim is informational only —
role is always re-read from the database to prevent token-based role escalation.

---

## Resource Authorization (Day 3)

### Data Model

```
User
  |
  | CaseMembership (case_id, user_id, role)
  v
Case
  |
  | FK: case.client_id → client.id
  v
Client
```

A User accesses a Client **only through** a Case they are a member of.
There is no direct User → Client relationship.

### Role Distinction

**System roles** (UserRole) — control global capabilities:

| Role | Capabilities |
|---|---|
| `ADMIN` | Full system access, bypasses all resource-level checks |
| `LAWYER` | Can create clients/cases; sees only cases where they hold a CaseMembership |
| `RESTRICTED_LAWYER` | Cannot create clients/cases; sees only cases where explicitly a member |

**Case roles** (CaseMemberRole) — control actions within a specific case:

| Role | Capabilities |
|---|---|
| `OWNER` | View, edit, manage members |
| `MEMBER` | View and edit |
| `VIEWER` | View only |

These are independent concepts. A `LAWYER` system role does not grant any
particular case role. Case access is always checked via `CaseMembership`.

### Authorization Flow

```
Request
  |
  v
get_current_user()          — Authentication: who are you?
  |
  v
Check resource access       — Authorization: can you access THIS resource?
  |
  +-- System-role check (require_role)
  |   e.g., RESTRICTED_LAWYER cannot create cases
  |
  +-- Case membership check (get_authorized_case / require_case_role)
  |   Non-members receive HTTP 404 (hides resource existence)
  |
  +-- Case role check (require_case_role(OWNER, MEMBER))
      VIEWER attempting edit receives HTTP 403
  |
  v
Database query (scoped to authorized resource set)
  |
  v
Return authorized resource
```

### Critical Security Invariant

**AUTHORIZATION MUST HAPPEN BEFORE RESOURCE RETRIEVAL.**

Never do this:
```python
# WRONG — fetches all cases, then filters
cases = db.query(Case).all()
return [c for c in cases if user in c.members]
```

Always do this:
```python
# CORRECT — authorization encoded in the SQL query
cases = (
    db.query(Case)
    .join(CaseMembership, CaseMembership.case_id == Case.id)
    .filter(CaseMembership.user_id == user.id)
    .all()
)
```

This principle extends to Day 4 documents and Day 5 vector search:
pgvector semantic search must be scoped to the user's authorized document set
**before** the similarity query executes.

### Resource-Hiding Strategy

Unauthorized access to a specific resource returns **HTTP 404** (not 403).

Rationale: returning 403 confirms the resource exists, which itself leaks
information to unauthorized users. Returning 404 uniformly prevents
enumeration of resources the user cannot access.

Exception: explicit system-role violations (e.g., RESTRICTED_LAWYER trying
to create a case) return 403 because the issue is the user's global role,
not the specific resource.

### Frontend Authorization

Frontend role checks (hiding "Create Case" for RESTRICTED_LAWYER, hiding
"Edit" for VIEWER) are **UX only — they are not security**.

The backend independently enforces all authorization on every request.
A determined user can bypass frontend role checks trivially. The backend
must never trust frontend claims about user roles or resource ownership.

### Document Permissions (Day 4)

Documents belong to Cases. The full authorization chain:

```
User
  |
  | CaseMembership (case_id, user_id, role)
  v
Case
  |
  | Document.case_id → Case.id
  v
Document
  |
  | DocumentChunk.document_id → Document.id
  v
DocumentChunk
  |
  | (Day 5)
  v
Embedding / pgvector
```

**Document access rules:**

| Action | Required case role |
|---|---|
| Upload | OWNER or MEMBER |
| List / View metadata | OWNER, MEMBER, or VIEWER |
| Download | OWNER, MEMBER, or VIEWER |
| List chunks | OWNER, MEMBER, or VIEWER |
| Delete | OWNER only |
| Any action | ADMIN bypasses all case checks |

Non-members receive HTTP 404 (resource-hiding, same policy as cases).

Any document retrieval query must be scoped to the user's authorized cases:
```sql
SELECT documents.*
FROM documents
JOIN case_memberships ON case_memberships.case_id = documents.case_id
WHERE case_memberships.user_id = :current_user_id;
```

Day 5 vector search must apply the same JOIN before the similarity query.

---

## Critical Security Principles

### Authorization Before Retrieval
**AUTHORIZATION MUST HAPPEN BEFORE RETRIEVAL.**

The eventual RAG pipeline must check user/case permissions before querying pgvector.
It must **never** retrieve document chunks first and filter afterward.
Pre-retrieval authorization is a hard architectural requirement.

### AI Agent Boundaries (Day 5+)
Future AI agents must **never** have unrestricted direct access to:
- PostgreSQL (only through the backend service layer)
- The filesystem (only through controlled document service APIs)
- Application secrets or environment variables
- The host machine or host network
- Arbitrary external network resources

All AI agent tool calls must go through permission-controlled service interfaces
that enforce the same access rules as human API calls.

### Data Boundaries
- The frontend never sees `DATABASE_URL`
- The frontend never sees `SECRET_KEY`
- The frontend never sees `LLM_API_KEY`
- All sensitive data stays server-side in the backend

---

## Technology Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 16, React 19, TypeScript, Tailwind CSS |
| Backend | Python 3.13, FastAPI, SQLAlchemy 2.x, Alembic |
| Database | PostgreSQL 17, pgvector |
| Infrastructure | Docker, Docker Compose |
| Testing | pytest, httpx, Jest (future) |
| Linting | ruff (Python), ESLint (TypeScript) |

---

## Future Architecture (Planned)

```
Browser
  |
Next.js Frontend
  |
FastAPI Backend
  |--- Auth middleware (JWT, Day 2)
  |--- Case service (Day 3)
  |--- Document service (Day 4)
  |--- RAG service (Day 5)
  |       |--- pgvector (permission-filtered)
  |       |--- LLM API
  |--- AI Agent service (Day 6)
          |--- Controlled tool boundaries
          |--- No direct DB/FS/secret access
  |
PostgreSQL + pgvector
```

---

## Document Ingestion Pipeline (Day 4)

### Pipeline

```
Upload
  → Validate (extension, magic bytes, size, empty)
  → SHA-256 checksum
  → Store (LocalStorage, UUID-based key, path-traversal prevention)
  → Extract text (pypdf / python-docx / UTF-8)
  → Normalize (line endings, whitespace)
  → Chunk (word-based sliding window, configurable size/overlap)
  → Persist DocumentChunk records
  → [Day 5: Embed → pgvector]
```

### Storage Abstraction

`LocalStorage` implements a minimal interface (`save`, `load`, `delete`, `exists`).
Switching to object storage (S3, GCS) requires only a new implementation of this interface.

Storage keys are always UUID-based (`{case_id}/{uuid4()}`). User-supplied filenames
are stored as `original_filename` (display only) and never used as filesystem paths.

### Text Extraction

| Format | Library | Limitation |
|---|---|---|
| PDF | pypdf 5.x | Text-based PDFs only; scanned/image PDFs yield FAILED status. OCR not supported. |
| DOCX | python-docx 1.x | Paragraphs + table cells |
| TXT | stdlib | UTF-8 required |

### Chunking

Word-based sliding window. Token counts are estimates: `words * 1.3` (no tokenizer dependency).

| Parameter | Default | Config key |
|---|---|---|
| Chunk size | 500 words ≈ 650 tokens | `CHUNK_SIZE_WORDS` |
| Overlap | 60 words ≈ 78 tokens | `CHUNK_OVERLAP_WORDS` |

### Embedding Provider Stub

`EmbeddingProvider` Protocol defined in `services/embedding_provider.py`.
Day 5 will implement a concrete provider and add embeddings to chunks.

### Processing Limitation

Processing is **synchronous** in Day 4. The upload HTTP request blocks until
extraction and chunking complete. For documents near 10 MB, this may be several
seconds. Recommended Day 5+ improvement: background job queue (Celery / ARQ).

---

## Day 1 Scope

Day 1 establishes the foundation only:
- Next.js frontend (dashboard placeholder)
- FastAPI backend (`GET /health`)
- PostgreSQL + pgvector (database ready, no business tables yet)
- Alembic (configured, no migrations yet)
- Docker Compose (all services wired)
- Environment configuration
- Basic tests

No authentication, no business logic, no AI features.
