# CaseVault — Demo Reference Guide

Concise commands and click sequence for the interview demo.
For full explanations, see [DEMO.md](DEMO.md).

---

## Prerequisites

```bash
# 1. Start PostgreSQL
cd infra && docker compose up postgres -d

# 2. Start backend (new terminal, from repo root)
cd backend && source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 3. Start frontend (new terminal, from repo root)
cd frontend && npm run dev

# Verify:
curl http://localhost:8000/health/ready
# {"status": "ok", "checks": {"database": "ok"}}
```

Open browser: **http://localhost:3000**

---

## Quick API Setup (copy-paste block)

```bash
BASE=http://localhost:8000

# Register + login
curl -s -X POST $BASE/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"alice@firm.com","password":"Demo1234!","full_name":"Alice Lawyer"}'

TOKEN=$(curl -s -X POST $BASE/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"alice@firm.com","password":"Demo1234!"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Create client + case
CLIENT_ID=$(curl -s -X POST $BASE/clients \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Acme Corporation","email":"legal@acme.example"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

CASE_ID=$(curl -s -X POST $BASE/cases \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"client_id\":\"$CLIENT_ID\",\"title\":\"Vendor Contract Review\",\"case_number\":\"VCR-2026-001\",\"status\":\"ACTIVE\"}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

echo "CASE_ID: $CASE_ID"
```

---

## Synthetic Documents

### Document 1 — vendor_contract.txt

```bash
cat > /tmp/vendor_contract.txt << 'EOF'
VENDOR SERVICES AGREEMENT

This agreement is between Acme Corporation ("Client") and Widget Supplier Inc. ("Vendor").
Effective date: March 1, 2025.

1. PAYMENT TERMS
Payment is due within 30 days of invoice receipt. Late payments accrue interest at 1.5%
per month. For invoices exceeding $50,000, Client may request a 45-day payment term.

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
```

### Document 2 — amendment_001.txt (creates a deliberate contradiction)

```bash
cat > /tmp/amendment_001.txt << 'EOF'
AMENDMENT NO. 1 TO VENDOR SERVICES AGREEMENT

This amendment is entered into on June 15, 2025, between Acme Corporation and Widget Supplier Inc.

1. PAYMENT TERMS AMENDMENT
Section 1 is hereby amended: Payment is now due within 45 days of invoice receipt
(previously 30 days). Interest on late payments remains at 1.5% per month.

2. TERMINATION AMENDMENT
Section 2 is hereby amended: The termination notice period is reduced to 30 days
(previously 60 days) for either party.

3. CONFIDENTIALITY AMENDMENT
The confidentiality period is extended to 7 years after termination
(previously 5 years).

This amendment supersedes the original agreement where in conflict.
EOF
```

### Upload both

```bash
curl -s -X POST "$BASE/cases/$CASE_ID/documents" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/tmp/vendor_contract.txt" | python3 -m json.tool

curl -s -X POST "$BASE/cases/$CASE_ID/documents" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/tmp/amendment_001.txt" | python3 -m json.tool
```

---

## Generate Embeddings

> Requires an ADMIN user. In development, you can promote a user via direct DB update,
> or use the seed script: `python scripts/seed_demo.py`

```bash
# If you have an ADMIN token:
curl -s -X POST $BASE/search/embed \
  -H "Authorization: Bearer $ADMIN_TOKEN" | python3 -m json.tool
# {"embedded": N}
```

---

## Semantic Search

```bash
curl -s -X POST $BASE/search \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"query\": \"payment terms\", \"case_id\": \"$CASE_ID\", \"limit\": 5}" \
  | python3 -m json.tool
```

**UI:** Navigate to Search → enter query → submit.

---

## RAG Chat + Citation Verification

```bash
curl -s -X POST $BASE/chat/ask \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"question\": \"What happens if a payment is late?\", \"case_id\": \"$CASE_ID\"}" \
  | python3 -m json.tool
```

Each source in the response now includes `verification_status`:
- **`verified`** — quoted text in the answer matches the stored source.
- **`unverified`** — source resolves but no exact quote was detected.
- **`invalid`** — a quoted passage was found but does not match the stored source.

**UI:** Navigate to Chat → select case → ask question.
Click any source card to open the citation detail modal. The modal re-fetches and re-verifies the source live from the database.

**Source detail endpoint:**
```bash
CHUNK_ID="<chunk_id from sources[0].chunk_id>"

# Re-verify without a quoted passage
curl -s "$BASE/chat/sources/$CHUNK_ID" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# Re-verify with a quoted passage
curl -s "$BASE/chat/sources/$CHUNK_ID?quoted_text=paid+within+30+days" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

**Without LLM key:** Returns 503 — not a crash. Show `pytest tests/test_citation_verification.py -v`.

---

## AI Agent

```bash
curl -s -X POST $BASE/agent/run \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"task\": \"What are the termination conditions?\", \"case_id\": \"$CASE_ID\"}" \
  | python3 -m json.tool
```

**UI:** Navigate to Agent → select case → enter task → Run agent.

---

## AI Case Timeline

```bash
# Analyze (requires LLM key)
curl -s -X POST "$BASE/cases/$CASE_ID/timeline/analyze" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"max_documents": 5, "force_reanalyze": false}' | python3 -m json.tool

# View events
curl -s "$BASE/cases/$CASE_ID/timeline" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# View contradictions (payment terms and termination notice differ between documents)
curl -s "$BASE/cases/$CASE_ID/contradictions" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

**UI:** Navigate to Cases → Vendor Contract Review → Timeline → Run Analysis.
Events appear on the timeline; the amendment creates payment and termination contradictions.

---

## Review a Contradiction

```bash
CONTRA_ID=$(curl -s "$BASE/cases/$CASE_ID/contradictions" \
  -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['contradictions'][0]['id'])")

curl -s -X PATCH "$BASE/cases/$CASE_ID/contradictions/$CONTRA_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"review_status": "REVIEWED"}' | python3 -m json.tool
```

**UI:** Expand contradiction card → click "REVIEWED".

---

## Permission Boundary Demo

```bash
# Register a second user with no case access
curl -s -X POST $BASE/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"bob@otherfirm.com","password":"Bob1234!","full_name":"Bob Smith"}'

BOB_TOKEN=$(curl -s -X POST $BASE/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"bob@otherfirm.com","password":"Bob1234!"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Bob cannot see Alice's case — 404, not 403 (resource-hiding)
curl -s "$BASE/cases/$CASE_ID" -H "Authorization: Bearer $BOB_TOKEN"

# Bob's search returns zero results (SQL JOIN requires CaseMembership)
curl -s -X POST $BASE/search \
  -H "Authorization: Bearer $BOB_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "payment terms", "limit": 10}' | python3 -m json.tool

# Bob cannot trigger timeline analysis — 404 (case not visible)
curl -s -X POST "$BASE/cases/$CASE_ID/timeline/analyze" \
  -H "Authorization: Bearer $BOB_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"max_documents": 5, "force_reanalyze": false}'
```

---

## Quality Gates (run these during demo)

```bash
# Backend tests (439 total)
cd backend && source .venv/bin/activate
pytest --tb=short -q

# Python lint
ruff check .

# TypeScript
cd ../frontend && npx tsc --noEmit

# ESLint
npm run lint

# Production build
npm run build
```

---

## Key Points to Highlight

| Topic | One-liner |
|---|---|
| Auth | JWT role re-read from DB every request — token escalation impossible |
| Authorization | SQL JOIN before retrieval — unauthorized data never in memory |
| Resource-hiding | 404 not 403 — prevents resource enumeration |
| Documents | Magic-byte validation + UUID storage keys + path-traversal guard |
| Embeddings | Local model, no API key, HNSW index, `vector(384)` column |
| Search | Authorization in SQL before `ORDER BY distance LIMIT k` |
| RAG | Server-side citation validation — fabricated [SOURCE:N] silently dropped |
| Citation verification | verified/unverified/invalid per citation; deterministic substring match; LLM cannot inject status |
| Agent | Tool allowlist; per-call authorization; JSON-in-prompt tool calling |
| Timeline | Quote verification — hallucinated sources rejected before persistence |
| Contradictions | Cross-document detection; severity ranking; review workflow |
| Observability | ContextVar request ID correlates all log lines for one request |
