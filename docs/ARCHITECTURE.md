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
