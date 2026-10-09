# CaseVault

**Intelligent Legal Case Management Platform**

CaseVault is an enterprise-grade platform for law firms and legal teams.
It combines structured case and document management with AI-powered semantic
document retrieval, enabling attorneys to surface relevant precedents and case
facts instantly.

> **Day 3 status:** Clients, cases, and resource-level authorization complete.
> Case memberships, scoped queries, and 81 backend tests are live.

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
- [x] `POST /clients` — create client (ADMIN/LAWYER only)
- [x] `GET /clients` — list clients (scoped by case membership)
- [x] `GET /clients/{id}` — get client (404 for unauthorized)
- [x] `PUT /clients/{id}` — update client (ADMIN or OWNER/MEMBER in case)
- [x] `DELETE /clients/{id}` — delete client (ADMIN only; 409 if cases exist)
- [x] `POST /cases` — create case (ADMIN/LAWYER; auto-creates OWNER membership)
- [x] `GET /cases` — list cases (scoped by membership)
- [x] `GET /cases/{id}` — get case (404 for non-members)
- [x] `PUT /cases/{id}` — update case (ADMIN/OWNER/MEMBER; 403 for VIEWER)
- [x] `DELETE /cases/{id}` — delete case (ADMIN/OWNER)
- [x] `POST /cases/{id}/members` — add member (ADMIN/OWNER)
- [x] `GET /cases/{id}/members` — list members (any case member)
- [x] `PUT /cases/{id}/members/{user_id}` — change role (ADMIN/OWNER)
- [x] `DELETE /cases/{id}/members/{user_id}` — remove member (ADMIN/OWNER; 400 for last OWNER)
- [x] `get_authorized_case()` dependency — database-scoped case access
- [x] `require_case_role()` dependency — case role enforcement
- [x] Clients page (`/clients`) — list + create
- [x] Cases page (`/cases`) — list + create
- [x] Case detail page (`/cases/[id]`) — info, client, members
- [x] Extended API client (`api.clients`, `api.cases`, `api.caseMembers`)
- [x] 81 backend tests (all pass, +58 Day 3 tests)
- [x] Resource isolation test: User A cannot access User B's cases
- [x] Architecture documentation updated

---

### Day 3 API Endpoints

```bash
# Clients
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/clients
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  http://localhost:8000/clients \
  -d '{"name":"Acme Corp","email":"acme@example.com"}'

# Cases
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/cases
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  http://localhost:8000/cases \
  -d '{"client_id":"<uuid>","case_number":"CASE-2026-001","title":"Acme v. Example"}'

# Case members
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/cases/<id>/members
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
| Document upload (PDF/DOCX) | Day 4 |
| Document chunking | Day 4 |
| Embeddings + pgvector search | Day 5 |
| RAG pipeline | Day 5 |
| LLM integration | Day 5 |
| AI chat interface | Day 6 |
| AI agents + tool calling | Day 6 |
| Audit logging | Day 7 |
| Production deployment | Day 8+ |
