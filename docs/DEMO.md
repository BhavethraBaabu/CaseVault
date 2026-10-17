# CaseVault — Interview Demo Script

**Duration:** 5–7 minutes
**Audience:** Software Engineer — Full Stack & AI Infrastructure interview

This script walks through the complete CaseVault workflow end-to-end.
Each step includes the action, expected result, the technical concept to highlight,
and a fallback if a live external provider (LLM, embeddings) is unavailable.

---

## Prerequisites

Before the demo, ensure:

1. Docker running, PostgreSQL container healthy:
   ```bash
   cd infra && docker compose up postgres -d
   # wait ~5s, then:
   curl http://localhost:8000/health/ready
   # {"status": "ok", "checks": {"database": "ok"}}
   ```

2. Backend running:
   ```bash
   cd backend && source .venv/bin/activate
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

3. Frontend running:
   ```bash
   cd frontend && npm run dev
   ```

4. (Optional) Set `LLM_API_KEY` in your `.env` for live RAG and agent demos.
   Without it, search and document upload still work; `/chat/ask` and `/agent/run`
   return 503 (see fallbacks below).

---

## Step 1 — Show the Health Endpoints (Observability)

**Action:**
```bash
# Liveness: is the process running?
curl http://localhost:8000/health/live

# Readiness: is the DB reachable?
curl http://localhost:8000/health/ready

# Provider configuration (no API calls made)
curl http://localhost:8000/health/config

# Request ID correlation
curl -H "X-Request-ID: demo-trace-001" http://localhost:8000/health/live
# Response header: X-Request-ID: demo-trace-001
```

**Expected result:**
```json
{"status": "ok"}
{"status": "ok", "checks": {"database": "ok"}}
{"status": "ok", "environment": "development", "providers": {"llm": "not_configured", "embedding": "local"}}
```

**Concept to explain:**
- Liveness vs. readiness: liveness checks that the process is alive; readiness checks that it can serve traffic (DB reachable). Used by Kubernetes probes.
- Request IDs are echoed in the response header and appear in every log line for that request. If a client reports `demo-trace-001`, you can grep logs and see the entire trace.
- The config endpoint confirms provider status without making live API calls — safe to call frequently.

---

## Step 2 — Register and Sign In

**Action (API):**
```bash
# Register
curl -s -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"alice@firm.com","password":"Demo1234!","full_name":"Alice Lawyer"}'

# Login and capture token
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"alice@firm.com","password":"Demo1234!"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Confirm identity
curl -s http://localhost:8000/auth/me -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

**Action (UI):** Navigate to http://localhost:3000/register, create an account, then log in.

**Concept to explain:**
- Passwords are hashed with bcrypt before storage — the plaintext never persists.
- The JWT contains only the user UUID (`sub`), role (informational), and expiry (`exp`).
- On every subsequent request, the role is **re-read from the database** — not trusted from the token. This prevents token-based role escalation if a role changes.

---

## Step 3 — Create a Client and Case

**Action (UI):**
1. Navigate to Clients → "New Client" → enter "Acme Corporation"
2. Navigate to Cases → "New Case" → select Acme Corporation, title "Vendor Contract Review", status ACTIVE

**Action (API):**
```bash
# Create client
CLIENT_ID=$(curl -s -X POST http://localhost:8000/clients \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Acme Corporation","email":"legal@acme.example"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# Create case
CASE_ID=$(curl -s -X POST http://localhost:8000/cases \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"client_id\":\"$CLIENT_ID\",\"title\":\"Vendor Contract Review\",\"case_number\":\"VCR-2026-001\",\"status\":\"ACTIVE\"}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "Case: $CASE_ID"
```

**Concept to explain:**
- The user who creates the case automatically becomes its OWNER (CaseMembership row).
- Resource-level authorization: a second user without a CaseMembership receives HTTP 404 — not 403. This hides the resource's existence from unauthorized users.

---

## Step 4 — Upload a Document

**Action:** Create a sample legal document file:
```bash
cat > /tmp/vendor_contract.txt << 'EOF'
VENDOR SERVICES AGREEMENT

This agreement is between Acme Corporation ("Client") and Widget Supplier Inc. ("Vendor").

1. PAYMENT TERMS
Payment is due within 30 days of invoice receipt. Late payments accrue interest at 1.5%
per month. For invoices exceeding $50,000, Client may request a 45-day payment term
by written notice no later than 10 days before invoice date.

2. TERMINATION
Either party may terminate this agreement with 60 days written notice. Immediate
termination is permitted for material breach not cured within 15 days of written notice.

3. INTELLECTUAL PROPERTY
All deliverables created under this agreement are work-for-hire and become the
exclusive property of Client upon full payment.

4. CONFIDENTIALITY
Both parties agree to maintain strict confidentiality for a period of 5 years after
termination. Confidential information includes pricing, trade secrets, and client lists.
EOF

# Upload
curl -s -X POST "http://localhost:8000/cases/$CASE_ID/documents" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/tmp/vendor_contract.txt" | python3 -m json.tool
```

**Action (UI):** Navigate to Cases → Vendor Contract Review → drag and drop `vendor_contract.txt`

**Expected result:** Document appears with status `READY`, page_count, and chunk count visible.

**Concept to explain:**
- Validation: extension whitelist + magic-byte verification (content-based, not name-based). A file named `malware.pdf` with ZIP magic bytes is rejected.
- Files are stored with UUID-based keys (`{case_id}/{uuid4}`), never derived from the filename. The `storage_key` is never exposed in API responses.
- Extraction → normalization → chunking (500-word sliding window, 60-word overlap) happens synchronously in the request. A production system would use a background job queue.

---

## Step 5 — Generate Embeddings

**Action:**
```bash
# Register an ADMIN user (required for /search/embed)
curl -s -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@firm.com","password":"Admin1234!","full_name":"Admin User"}'
# (In a real setup, promote to ADMIN via direct DB update or an admin endpoint)

# If you have an ADMIN token:
ADMIN_TOKEN=<your-admin-token>
curl -s -X POST http://localhost:8000/search/embed \
  -H "Authorization: Bearer $ADMIN_TOKEN" | python3 -m json.tool
# {"embedded": 4}
```

**Concept to explain:**
- `sentence-transformers/all-MiniLM-L6-v2` runs locally, no API key required.
- Each chunk gets a 384-dimensional vector. The vector is stored in a `vector(384)` PostgreSQL column indexed with HNSW (Hierarchical Navigable Small World) for approximate nearest-neighbor search.
- The `EmbeddingVector` TypeDecorator handles `vector(384)` in PostgreSQL and JSON TEXT in SQLite (for tests).

**Fallback (no PG/embedding available):** Show the test output:
```bash
cd backend && source .venv/bin/activate
pytest tests/test_embedding.py tests/test_search.py -v
```

---

## Step 6 — Semantic Search

**Action:**
```bash
curl -s -X POST http://localhost:8000/search \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "What are the payment terms?", "limit": 3}' | python3 -m json.tool
```

**Action (UI):** Navigate to Search → enter "What are the payment terms?" → submit.

**Expected result:** Chunks from the vendor contract with similarity scores.

**Concept to explain:**
- Authorization is encoded in the SQL JOIN/WHERE **before** `ORDER BY distance LIMIT k`. Unauthorized chunks never appear in results, even in discarded positions.
- The query text is embedded at search time; the resulting vector is compared against stored chunk vectors using cosine distance (`<=>` operator). Similarity = `1 - cosine_distance`.
- Try a cross-user isolation demo: register a second user (Bob), do NOT add Bob to the case, search as Bob → 0 results. The SQL JOIN requires CaseMembership.

---

## Step 7 — RAG Chat

**Action:**
```bash
curl -s -X POST http://localhost:8000/chat/ask \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"question\": \"What happens if a payment is late?\", \"case_id\": \"$CASE_ID\"}" \
  | python3 -m json.tool
```

**Action (UI):** Navigate to Chat → select "Vendor Contract Review" → ask "What happens if a payment is late?"

**Expected result (with LLM key):**
```json
{
  "answer": "According to [SOURCE:1], late payments accrue interest at 1.5% per month.",
  "citations": [
    {
      "document_name": "vendor_contract.txt",
      "page_number": 1,
      "excerpt": "Late payments accrue interest at 1.5% per month...",
      "similarity": 0.91
    }
  ],
  "insufficient_evidence": false
}
```

**Concept to explain:**
1. Retrieved chunks are numbered `[SOURCE:1]`, `[SOURCE:2]` in the prompt. The LLM is instructed to cite only using these references.
2. **Citation validation** (key security point): after the LLM responds, the backend checks every `[SOURCE:N]` against the retrieved set. Fabricated indices are silently discarded. The client only sees validated, authorized citations.
3. If no relevant chunks are found → `insufficient_evidence: true` and the LLM is never called (cost saving + no hallucination risk).
4. Conversation history: subsequent messages in the same conversation get the last `rag_history_messages` (default: 10) prepended.

**Fallback (no LLM key):**
```bash
# Shows 503 with a clear message — not a crash
curl -s -X POST http://localhost:8000/chat/ask \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question": "What are the payment terms?"}' | python3 -m json.tool
# {"detail": "AI service unavailable. Configure LLM_API_KEY to enable chat."}

# Show the RAG tests work deterministically with fake providers:
pytest tests/test_rag.py -v
```

---

## Step 8 — AI Agent

**Action:**
```bash
curl -s -X POST http://localhost:8000/agent/run \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"task\": \"What are the termination conditions in the vendor contract?\", \"case_id\": \"$CASE_ID\"}" \
  | python3 -m json.tool
```

**Action (UI):** Navigate to Agent → select case → enter task → Run agent.

**Expected result (with LLM key):**
```json
{
  "answer": "According to [SOURCE:1], either party may terminate with 60 days written notice...",
  "tools_executed": [
    {"tool_name": "search_documents", "success": true}
  ],
  "citations": [...],
  "status": "success"
}
```

**Concept to explain:**
- The agent loop: build system prompt → LLM → parse JSON response → validate tool → execute → add result to context → repeat.
- **Tool allowlist**: `ALLOWED_TOOL_NAMES = {search_documents, list_cases, get_case_details, get_document_context}`. Any tool name not in this set is rejected before execution. The LLM cannot call OS commands or access arbitrary files.
- **Identity**: the user comes from the JWT on the HTTP request, never from the task text or LLM output.
- **Per-call authorization**: even if the LLM calls `get_case_details` with a different `case_id`, the tool independently re-checks membership.
- **JSON-in-prompt** (not OpenAI function calling): works with any LLM, fully testable with `FakeSequentialProvider`.

**Fallback (no LLM key):** Show tests:
```bash
pytest tests/test_agent.py tests/test_agent_tools.py -v
```

---

## Step 9 — Permission Boundary Demo

**Concept to explain:** Authorization is enforced server-side, not just hidden in the UI.

```bash
# Register a second user
curl -s -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"bob@otherfirm.com","password":"Bob1234!","full_name":"Bob Smith"}'

BOB_TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"bob@otherfirm.com","password":"Bob1234!"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Bob tries to access Alice's case
curl -s "http://localhost:8000/cases/$CASE_ID" \
  -H "Authorization: Bearer $BOB_TOKEN"
# HTTP 404 — not 403. Resource-hiding: Bob cannot confirm the case exists.

# Bob searches — gets 0 results (SQL JOIN requires CaseMembership)
curl -s -X POST http://localhost:8000/search \
  -H "Authorization: Bearer $BOB_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "payment terms", "limit": 10}' | python3 -m json.tool
# {"results": [], "total": 0, ...}
```

**Key point:** The frontend route guard (redirect to login) can be bypassed by sending raw API requests. The backend independently enforces authorization on every request.

---

## Step 10 — Quality Gates Summary

Show the verified test results:

```bash
# All 359 backend tests
cd backend && source .venv/bin/activate
pytest --tb=short -q
# 359 passed in ~150s

# Ruff (Python lint)
ruff check .
# All checks passed!

# TypeScript
cd frontend && npx tsc --noEmit
# (no output = clean)

# ESLint
npm run lint
# (no output = clean)

# Production build
npm run build
# ✓ Generating static pages (12/12)
```

---

## Honest Limitations to Disclose

If asked about production readiness, be transparent:

1. **Real LLM not tested**: All 359 tests use `FakeLLMProvider` / `FakeSequentialProvider`. Real OpenAI API compliance with the JSON-in-prompt format is not verified in automated tests.
2. **PostgreSQL + pgvector not live-tested**: All tests use SQLite in-memory. pgvector operators, HNSW index, and Alembic migrations have not been exercised against a live PostgreSQL in CI.
3. **No JWT revocation**: Logout is client-side. A stolen token remains valid until expiry.
4. **No rate limiting**: Brute-force on `/auth/login` is unprotected at the application layer. Requires a reverse proxy.
5. **Synchronous extraction**: Large documents block the HTTP worker. No background queue.
6. **Prompt injection**: Cannot be fully prevented. The backend validates citations and authorization regardless of LLM output.

---

## Talking Points by Technical Area

| Area | Key talking point |
|---|---|
| Auth | JWT role re-read from DB every request; bcrypt directly (no passlib) |
| Authorization | SQL JOIN before retrieval; 404 not 403 for resource-hiding |
| Documents | Magic-byte validation; UUID storage keys; path-traversal guard |
| Embeddings | Local model, no API key; HNSW index; `vector(384)` column |
| Search | Authorization encoded in SQL before `ORDER BY distance LIMIT k` |
| RAG | Citation validation server-side; INSUFFICIENT_EVIDENCE sentinel |
| Agent | Tool allowlist; per-call authorization; JSON-in-prompt tool calling |
| Observability | ContextVar request ID; structured logging; liveness vs. readiness |
| Security | Defence-in-depth; configurable CORS; security headers; safe errors |
