# CaseVault

**Intelligent Legal Case Management Platform**

CaseVault is an enterprise-grade platform for law firms and legal teams.
It combines structured case and document management with AI-powered semantic
document retrieval, enabling attorneys to surface relevant precedents and case
facts instantly.

> **Day 5 status:** Embedding generation and semantic search complete.
> Upload → Extract → Chunk → Embed → pgvector Search, with full case-level authorization.
> 154 backend tests pass. LLM answer generation (RAG) is Day 6.

---

## Architecture Overview

```
Browser → Next.js (3000) → FastAPI (8000) → PostgreSQL + pgvector (5432)
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full architecture, security
principles, and future design.

---

## Technology Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 16, React 19, TypeScript, Tailwind CSS |
| Backend | Python 3.13, FastAPI, SQLAlchemy 2.x, Alembic |
| Database | PostgreSQL 17 + pgvector |
| Infrastructure | Docker, Docker Compose |
| Testing | pytest, httpx |
| Linting | ruff (Python), ESLint (TypeScript) |

---

## Project Structure

```
CaseVault/
├── frontend/               # Next.js App Router
│   ├── app/                # Pages and layouts
│   ├── components/         # Reusable UI components
│   ├── lib/                # API client and utilities
│   └── public/             # Static assets
├── backend/                # FastAPI application
│   ├── app/
│   │   ├── api/v1/         # Route handlers
│   │   ├── core/           # Config and settings
│   │   ├── db/             # SQLAlchemy session
│   │   ├── models/         # ORM models (Day 2+)
│   │   ├── schemas/        # Pydantic schemas
│   │   ├── services/       # Business logic (Day 2+)
│   │   └── main.py
│   ├── alembic/            # Database migrations
│   ├── tests/              # Backend tests
│   ├── requirements.txt
│   └── Dockerfile
├── infra/
│   ├── docker-compose.yml  # Full stack Docker Compose
│   └── postgres/
│       └── init.sql        # pgvector initialization
├── docs/
│   └── ARCHITECTURE.md
├── .env.example            # Environment variable template
├── .gitignore
└── README.md
```

---

## Environment Configuration

Copy `.env.example` to `.env` and fill in values:

```bash
cp .env.example .env
```

Key variables:

| Variable | Description |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `NEXT_PUBLIC_API_URL` | Backend URL (exposed to browser) |
| `SECRET_KEY` | JWT signing secret — generate with `python -c "import secrets; print(secrets.token_hex(32))"` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | JWT lifetime in minutes (default: 30) |
| `DOCUMENT_STORAGE_PATH` | Absolute path for uploaded file storage (default: `backend/storage/documents`) |
| `MAX_UPLOAD_SIZE_BYTES` | Max upload size in bytes (default: 10485760 = 10 MB) |
| `CHUNK_SIZE_WORDS` | Target words per chunk (default: 500 ≈ 650 tokens) |
| `CHUNK_OVERLAP_WORDS` | Overlap words between chunks (default: 60 ≈ 78 tokens) |
| `EMBEDDING_MODEL` | Sentence-transformers model (default: `sentence-transformers/all-MiniLM-L6-v2`) |
| `EMBEDDING_DIM` | Vector dimension — must match model and DB column (default: 384) |
| `EMBEDDING_BATCH_SIZE` | Chunks per embedding batch (default: 64) |
| `SEARCH_DEFAULT_LIMIT` | Default results per search (default: 10) |
| `SEARCH_MAX_LIMIT` | Hard cap per request (default: 50) |
| `LLM_API_KEY` | LLM provider key (Day 6+) |

**Never commit `.env` to version control.**

---

## Local Development (without Docker)

### Prerequisites

- Node.js 18+
- Python 3.11+
- PostgreSQL 15+ with pgvector (or use Docker for just the database)

### Start PostgreSQL only

```bash
cd infra
docker compose up postgres -d
```

### Backend

```bash
cd backend

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Set environment variables
cp ../.env.example .env
# Edit .env with your values

# Start the backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd frontend

# Install dependencies
npm install

# Set environment variables
cp .env.local.example .env.local
# Edit .env.local if needed

# Start the frontend
npm run dev
```

Frontend available at: http://localhost:3000

---

## Docker Compose

Run the full stack (PostgreSQL + backend + frontend):

```bash
cd infra
docker compose up --build
```

Or in the background:

```bash
docker compose up --build -d
```

Stop:

```bash
docker compose down
```

Stop and remove volumes (destroys database data):

```bash
docker compose down -v
```

---

## Health Check

```bash
curl http://localhost:8000/health
```

Expected:

```json
{"status": "ok", "version": "0.1.0", "database": "ok"}
```

API docs (Swagger UI): http://localhost:8000/docs

---

## Authentication

### How it works

1. **Register** — `POST /auth/register` creates a user with bcrypt-hashed password. Default role: `LAWYER`.
2. **Login** — `POST /auth/login` returns a signed JWT (`access_token`).
3. **Protected requests** — include `Authorization: Bearer <token>` header.
4. **Token validation** — backend validates signature, expiration, user existence, and active status on every request.
5. **Logout** — client discards the token. Stateless JWT: token is not server-side invalidated.

### Roles

| Role | Description |
|---|---|
| `ADMIN` | Full system access |
| `LAWYER` | Standard authenticated access |
| `RESTRICTED_LAWYER` | Limited scope (enforced in Day 3+) |

### Quick test

```bash
# Register
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"jane@firm.com","password":"Secret123!","full_name":"Jane Lawyer"}'

# Login
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"jane@firm.com","password":"Secret123!"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Authenticated request
curl http://localhost:8000/auth/me -H "Authorization: Bearer $TOKEN"
```

---

## Running Tests

### Backend tests

```bash
cd backend
source .venv/bin/activate
pytest
```

With coverage:

```bash
pytest --cov=app --cov-report=term-missing
```

### Frontend type check

```bash
cd frontend
npx tsc --noEmit
```

### Frontend lint

```bash
cd frontend
npm run lint
```

---

## Database Migrations (Alembic)

```bash
cd backend
source .venv/bin/activate

# Check current revision
alembic current

# Create a new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Roll back one step
alembic downgrade -1
```

---

## Day 1 Scope

- [x] Next.js frontend with dashboard placeholder
- [x] FastAPI backend with `GET /health`
- [x] PostgreSQL + pgvector (database ready)
- [x] Alembic configured
- [x] Docker Compose for full stack
- [x] Environment configuration
- [x] Basic backend tests
- [x] Architecture documentation

## Day 2 Scope

- [x] User model with UUID, bcrypt-hashed password, role enum
- [x] Alembic migration: `users` table
- [x] `POST /auth/register` — register with email + password
- [x] `POST /auth/login` — returns JWT access token
- [x] `GET /auth/me` — returns current authenticated user
- [x] `POST /auth/logout` — client-side token removal
- [x] `get_current_user()` FastAPI dependency
- [x] `require_role()` authorization helper
- [x] Login page (`/login`)
- [x] Register page (`/register`)
- [x] Protected dashboard (redirects to `/login` when unauthenticated)
- [x] Auth context + localStorage token management
- [x] 23 backend tests (all pass)

## Day 3 Scope

- [x] `Client` model — UUID, name, email, phone, organization
- [x] `Case` model — UUID, client_id FK, case_number (unique), title, status enum
- [x] `CaseMembership` model — case_id + user_id (unique), role enum
- [x] Alembic migration: `clients`, `cases`, `case_memberships` tables
- [x] Full CRUD for clients, cases, and memberships
- [x] `get_authorized_case()` + `require_case_role()` dependencies
- [x] Frontend: `/clients`, `/cases`, `/cases/[id]`
- [x] 81 backend tests (all pass)

## Day 4 Scope

- [x] `Document` model — UUID, case_id FK, uploaded_by FK, filename, storage_key, content_type, file_size, file_hash, status, page_count, error_message
- [x] `DocumentChunk` model — UUID, document_id FK, chunk_index, content (Text), token_count (estimated), page_number
- [x] Alembic migration `0003_create_documents_chunks`
- [x] `POST /cases/{case_id}/documents` — upload (OWNER/MEMBER only)
- [x] `GET /cases/{case_id}/documents` — list (any case member)
- [x] `GET /documents/{document_id}` — metadata (any case member; 404 for non-members)
- [x] `GET /documents/{document_id}/download` — binary download (any case member)
- [x] `GET /documents/{document_id}/chunks` — chunk list (any case member)
- [x] `DELETE /documents/{document_id}` — delete + chunks + file (OWNER/ADMIN)
- [x] File validation: extension whitelist, content-based magic-byte verification, size limit, empty file rejection
- [x] Text extraction: PDF (pypdf, text-based), DOCX (python-docx), TXT (UTF-8)
- [x] Text normalization: line endings, whitespace, paragraph boundaries
- [x] Overlapping chunking: configurable word-based windows with documented token approximation
- [x] `LocalStorage` abstraction with path-traversal prevention
- [x] `EmbeddingProvider` Protocol stub (interface only; Day 5 fills implementation)
- [x] `get_authorized_document()` + `require_document_case_role()` dependencies
- [x] Frontend: document upload, list, download, delete on `/cases/[id]`
- [x] 36 new document tests; 117 total (all pass)
- [x] storage_key never exposed in API responses

### Known Limitations (Day 4)

- **Scanned PDFs**: pypdf cannot extract text from image-based PDFs. OCR is not supported.
- **Synchronous processing**: extraction and chunking happen in the HTTP request.
- **Local storage only**: files are stored on the server filesystem.
- **SQLite tests**: do not validate PostgreSQL-specific behavior.

## Day 5 Scope

- [x] `SentenceTransformerProvider` — `all-MiniLM-L6-v2` (384-dim, CPU, ~90 MB), lazy singleton
- [x] `FakeEmbeddingProvider` — deterministic vectors for unit tests; no model download
- [x] `EmbeddingVector` TypeDecorator — `vector(384)` in PostgreSQL, JSON `TEXT` in SQLite
- [x] Alembic migration `0004_add_embeddings` — pgvector extension, embedding column, HNSW index
- [x] `embedding_status` lifecycle (`PENDING` → `READY`/`FAILED`) on `DocumentChunk`
- [x] `embed_document_chunks()` — embed all chunks for a single document
- [x] `embed_pending_chunks()` — batch-embed all unembedded chunks (idempotent)
- [x] `POST /search` — semantic search endpoint (authenticated, all roles)
- [x] `POST /search/embed` — trigger batch embedding (ADMIN only)
- [x] Authorization-before-ranking: JOIN/WHERE applied before `ORDER BY distance LIMIT k`
- [x] Cross-case isolation: User A and User B cannot access each other's results
- [x] Frontend: `/search` page with query input, case filter, result cards, similarity %
- [x] Navbar: Search link added
- [x] 37 new tests; 154 total (all pass)
- [x] No embedding vectors returned in API responses
- [x] No AI answer generation (Day 6)

### Day 5 Embedding Model

| Property | Value |
|---|---|
| Model | `sentence-transformers/all-MiniLM-L6-v2` |
| Dimension | 384 |
| Download size | ~90 MB (first use only) |
| RAM usage | ~200–350 MB on CPU |
| Why local | No API key required; deterministic; free |
| Free-tier warning | Some 512 MB RAM instances may OOM; verify before deploying |

### Day 5 Vector Search

| Property | Value |
|---|---|
| Storage | pgvector `vector(384)` column |
| Distance metric | Cosine distance (`<=>` operator) |
| Similarity score | `1 − cosine_distance` ∈ [0, 1] |
| Index | HNSW (`vector_cosine_ops`, m=16, ef_construction=64) |
| Authorization | SQL JOIN before ORDER BY + LIMIT (never post-filter) |
| SQLite fallback | Python cosine similarity for unit tests |

### Generating Embeddings

After uploading documents, generate embeddings (ADMIN only):

```bash
# Trigger batch embedding for all unembedded chunks
curl -X POST http://localhost:8000/search/embed \
  -H "Authorization: Bearer $ADMIN_TOKEN"
# {"embedded": 42}
```

### Semantic Search

```bash
# Search across all accessible cases
curl -X POST http://localhost:8000/search \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "What does the contract say about termination?", "limit": 5}'

# Search within a specific case
curl -X POST http://localhost:8000/search \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "payment schedule", "case_id": "<uuid>", "limit": 10}'
```

### Known Limitations (Day 5)

- **Model download**: `all-MiniLM-L6-v2` requires ~90 MB download on first use.
- **Synchronous embedding**: embedding blocks the `/search/embed` request; not suitable for bulk jobs on large datasets without a task queue.
- **SQLite isolation**: SQLite tests verify authorization logic but NOT pgvector operators, HNSW index, or extension creation. Live PostgreSQL was unavailable during development (Docker not running). PostgreSQL-specific checks remain outstanding.
- **No RAG**: search returns raw chunk content only. LLM answer generation is Day 6.
- **No re-embedding on model change**: changing `EMBEDDING_MODEL` requires running `/search/embed` again; old embeddings are replaced automatically.

### Day 5 API Endpoints

```bash
# Upload a document (multipart/form-data)
curl -X POST http://localhost:8000/cases/<case_id>/documents \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@contract.pdf"

# List documents in a case
curl http://localhost:8000/cases/<case_id>/documents \
  -H "Authorization: Bearer $TOKEN"

# Get document metadata
curl http://localhost:8000/documents/<doc_id> \
  -H "Authorization: Bearer $TOKEN"

# Download original file
curl http://localhost:8000/documents/<doc_id>/download \
  -H "Authorization: Bearer $TOKEN" -o downloaded.pdf

# List chunks
curl http://localhost:8000/documents/<doc_id>/chunks \
  -H "Authorization: Bearer $TOKEN"

# Delete document
curl -X DELETE http://localhost:8000/documents/<doc_id> \
  -H "Authorization: Bearer $TOKEN"

# Semantic search
curl -X POST http://localhost:8000/search \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "termination clause", "limit": 5}'

# Generate embeddings (ADMIN only)
curl -X POST http://localhost:8000/search/embed \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

---

## Intentionally Postponed

| Feature | Day |
|---|---|
| Authentication (JWT, sessions) | Day 2 ✓ |
| User roles and permissions | Day 2 ✓ |
| Case management | Day 3 ✓ |
| Client management | Day 3 ✓ |
| Document ingestion | Day 4 ✓ |
| Embeddings + pgvector search | Day 5 ✓ |
| LLM answer generation (RAG) | Day 6 |
| AI chat interface | Day 6 |
| AI agents + tool calling | Day 7 |
| Audit logging | Day 8 |
| Production deployment | Day 9+ |
