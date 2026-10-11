# CaseVault

**Intelligent Legal Case Management Platform**

CaseVault is an enterprise-grade platform for law firms and legal teams.
It combines structured case and document management with AI-powered semantic
document retrieval, enabling attorneys to surface relevant precedents and case
facts instantly.

> **Day 4 status:** Secure document ingestion pipeline complete.
> Upload, extract, chunk, and manage documents with full case-level authorization.
> 117 backend tests pass. Embedding generation and vector search are Day 5.

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
| `LLM_API_KEY` | LLM provider key (Day 5+) |
| `EMBEDDING_API_KEY` | Embedding provider key (Day 5+) |

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

- **Scanned PDFs**: pypdf cannot extract text from image-based PDFs. OCR is not supported. Such documents receive status `FAILED` with an informative error message.
- **Synchronous processing**: extraction and chunking happen in the HTTP request. This may add latency for large files near the 10 MB limit. A background-job queue (Celery, ARQ) is the recommended Day 5+ improvement.
- **Local storage only**: files are stored on the server filesystem. Object storage (S3, GCS) can be added by implementing the `LocalStorage` interface.
- **In-memory downloads**: files are loaded entirely into memory before streaming. Acceptable for the 10 MB dev limit; replace with streaming for production.
- **SQLite tests**: in-memory SQLite tests do not validate PostgreSQL-specific behavior (e.g. pgvector, `UUID` type). Live PostgreSQL validation requires a running database.

### Day 4 API Endpoints

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
```

---

## Intentionally Postponed

The following features are scheduled for later days and are **not** in Day 1:

| Feature | Day |
|---|---|
| Authentication (JWT, sessions) | Day 2 |
| User roles and permissions | Day 2 |
| Case management | Day 3 |
| Client management | Day 3 |
| Embeddings + pgvector search | Day 5 |
| RAG pipeline | Day 5 |
| LLM integration | Day 5 |
| AI chat interface | Day 6 |
| AI agents + tool calling | Day 6 |
| Audit logging | Day 7 |
| Production deployment | Day 8+ |
