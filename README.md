# CaseVault

**Intelligent Legal Case Management Platform**

CaseVault is an enterprise-grade platform for law firms and legal teams.
It combines structured case and document management with AI-powered semantic
document retrieval, enabling attorneys to surface relevant precedents and case
facts instantly.

> **Day 1 status:** Foundation only — infrastructure, API skeleton, database ready.
> Authentication, case management, and AI features are scheduled for later days.

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
| `SECRET_KEY` | Application secret (generate with `python -c "import secrets; print(secrets.token_hex(32))"`) |
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

Once the backend is running:

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{
  "status": "ok",
  "version": "0.1.0",
  "database": "ok"
}
```

API documentation (Swagger UI): http://localhost:8000/docs

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

What is implemented in Day 1:

- [x] Next.js frontend with dashboard placeholder
- [x] FastAPI backend with `GET /health`
- [x] PostgreSQL + pgvector (database ready)
- [x] Alembic configured (no business migrations yet)
- [x] Docker Compose for full stack
- [x] Environment configuration
- [x] Basic backend tests
- [x] Architecture documentation

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
