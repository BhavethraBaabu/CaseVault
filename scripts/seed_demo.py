#!/usr/bin/env python3
"""
CaseVault demo seed script.

Creates synthetic legal case data suitable for the interview demo.

What it does
------------
1. Registers two users (alice LAWYER, admin ADMIN).
2. Creates a client (Acme Corporation).
3. Creates a case (Vendor Contract Review).
4. Uploads two synthetic text documents:
   - vendor_contract.txt  — original agreement
   - amendment_001.txt    — amendment that contradicts the original on 3 points
     (payment terms: 30 days → 45 days, termination notice: 60 days → 30 days,
      confidentiality period: 5 years → 7 years)
5. Promotes the admin user to ADMIN role via the database.
6. Generates embeddings for all uploaded chunks (ADMIN only).

Usage
-----
    cd backend
    source .venv/bin/activate
    python ../scripts/seed_demo.py

Requirements
------------
- Backend must be running at http://localhost:8000
- PostgreSQL must be running with the schema migrated (alembic upgrade head)
- DATABASE_URL must be set (used only for the ADMIN promotion step)

This script is safe to run repeatedly.  If the email already exists,
registration is skipped.  If the case already exists, document upload is
skipped.  No data is deleted.

WARNING: This script uses hard-coded synthetic credentials for demo purposes.
         Never use these credentials in a production environment.
"""

import json
import os
import sys
import textwrap
import urllib.error
import urllib.request

BASE_URL = os.getenv("CASEVAULT_BASE_URL", "http://localhost:8000")

ALICE_EMAIL = "alice@firm.com"
ALICE_PASSWORD = "Demo1234!"
ALICE_NAME = "Alice Lawyer"

ADMIN_EMAIL = "admin@firm.com"
ADMIN_PASSWORD = "Admin1234!"
ADMIN_NAME = "Admin User"

VENDOR_CONTRACT = textwrap.dedent("""\
    VENDOR SERVICES AGREEMENT

    This agreement is between Acme Corporation ("Client") and Widget Supplier Inc. ("Vendor").
    Effective date: March 1, 2025.

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
""")

AMENDMENT_001 = textwrap.dedent("""\
    AMENDMENT NO. 1 TO VENDOR SERVICES AGREEMENT

    This amendment is entered into on June 15, 2025, between Acme Corporation ("Client")
    and Widget Supplier Inc. ("Vendor").

    1. PAYMENT TERMS AMENDMENT
    Section 1 is hereby amended: Payment is now due within 45 days of invoice receipt
    (previously 30 days). Interest on late payments remains at 1.5% per month.

    2. TERMINATION AMENDMENT
    Section 2 is hereby amended: The termination notice period is reduced to 30 days
    (previously 60 days) for either party. Immediate termination provisions remain unchanged.

    3. CONFIDENTIALITY AMENDMENT
    The confidentiality period is extended to 7 years after termination
    (previously 5 years). All other confidentiality terms remain in effect.

    This amendment supersedes the original Vendor Services Agreement where in conflict.
    All other terms and conditions of the original agreement remain in full force and effect.
""")


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _request(
    method: str,
    path: str,
    body: dict | None = None,
    token: str | None = None,
    multipart: bytes | None = None,
    content_type: str | None = None,
) -> dict:
    url = BASE_URL + path
    data: bytes | None = None
    headers: dict[str, str] = {}

    if token:
        headers["Authorization"] = f"Bearer {token}"

    if multipart is not None:
        data = multipart
        if content_type:
            headers["Content-Type"] = content_type
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode(errors="replace")
        if e.code == 409:
            # Already exists — return empty sentinel
            return {"_conflict": True, "_detail": body_text}
        raise RuntimeError(f"HTTP {e.code} {method} {path}: {body_text}") from e


def _multipart_upload(path: str, token: str, filename: str, content: str) -> dict:
    """Upload a text file as multipart/form-data."""
    boundary = "----CaseVaultSeedBoundary"
    file_bytes = content.encode("utf-8")
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: text/plain\r\n"
        f"\r\n"
    ).encode() + file_bytes + f"\r\n--{boundary}--\r\n".encode()
    return _request(
        "POST",
        path,
        multipart=body,
        token=token,
        content_type=f"multipart/form-data; boundary={boundary}",
    )


# ---------------------------------------------------------------------------
# Seed steps
# ---------------------------------------------------------------------------


def register_user(email: str, password: str, full_name: str) -> dict | None:
    result = _request("POST", "/auth/register", {
        "email": email,
        "password": password,
        "full_name": full_name,
    })
    if result.get("_conflict"):
        print(f"  [skip] {email} already registered")
        return None
    print(f"  [ok]   Registered {email}")
    return result


def login(email: str, password: str) -> str:
    result = _request("POST", "/auth/login", {"email": email, "password": password})
    token = result["access_token"]
    print(f"  [ok]   Logged in as {email}")
    return token


def promote_admin(admin_email: str) -> None:
    """Promote a user to ADMIN role via direct DB update."""
    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        print("  [skip] DATABASE_URL not set — skipping ADMIN promotion")
        print("         Set ADMIN role manually: UPDATE users SET role='ADMIN' WHERE email='admin@firm.com';")
        return

    try:
        import sqlalchemy  # noqa: PLC0415

        engine = sqlalchemy.create_engine(db_url)
        with engine.begin() as conn:
            result = conn.execute(
                sqlalchemy.text(
                    "UPDATE users SET role = 'ADMIN' WHERE email = :email"
                ),
                {"email": admin_email},
            )
            if result.rowcount > 0:
                print(f"  [ok]   Promoted {admin_email} to ADMIN")
            else:
                print(f"  [warn] {admin_email} not found in DB — run registration first")
    except Exception as exc:  # noqa: BLE001
        print(f"  [warn] Could not promote admin: {exc}")
        print("         Set ADMIN role manually: UPDATE users SET role='ADMIN' WHERE email='admin@firm.com';")


def main() -> None:
    print("=== CaseVault Demo Seed Script ===")
    print(f"Backend: {BASE_URL}")
    print()

    # 1. Health check
    print("[1] Health check")
    try:
        health = _request("GET", "/health/live")
        print(f"  [ok]   {health}")
    except Exception as exc:
        print(f"  [FAIL] Backend not reachable: {exc}")
        sys.exit(1)

    # 2. Register users
    print("\n[2] Registering users")
    register_user(ALICE_EMAIL, ALICE_PASSWORD, ALICE_NAME)
    register_user(ADMIN_EMAIL, ADMIN_PASSWORD, ADMIN_NAME)

    # 3. Promote admin
    print("\n[3] Promoting admin user")
    promote_admin(ADMIN_EMAIL)

    # 4. Login
    print("\n[4] Logging in")
    alice_token = login(ALICE_EMAIL, ALICE_PASSWORD)
    admin_token = login(ADMIN_EMAIL, ADMIN_PASSWORD)

    # 5. Create client
    print("\n[5] Creating client")
    client_result = _request("POST", "/clients", {
        "name": "Acme Corporation",
        "email": "legal@acme.example",
        "organization": "Acme Corporation",
    }, token=alice_token)
    if client_result.get("_conflict"):
        # Search for existing
        clients = _request("GET", "/clients", token=alice_token)
        client_id = next(
            (c["id"] for c in clients.get("clients", []) if c["name"] == "Acme Corporation"),
            None,
        )
        if client_id:
            print(f"  [skip] Client exists: {client_id}")
        else:
            print("  [warn] Could not find existing client")
            client_id = None
    else:
        client_id = client_result["id"]
        print(f"  [ok]   Client: {client_id}")

    if not client_id:
        print("  [FAIL] No client ID — aborting")
        sys.exit(1)

    # 6. Create case
    print("\n[6] Creating case")
    case_result = _request("POST", "/cases", {
        "client_id": client_id,
        "title": "Vendor Contract Review",
        "case_number": "VCR-2026-001",
        "status": "ACTIVE",
        "description": "Review of vendor services agreement and amendment for payment and termination discrepancies.",
    }, token=alice_token)
    if case_result.get("_conflict"):
        cases = _request("GET", "/cases", token=alice_token)
        case_id = next(
            (c["id"] for c in cases.get("cases", []) if c["case_number"] == "VCR-2026-001"),
            None,
        )
        if case_id:
            print(f"  [skip] Case exists: {case_id}")
        else:
            print("  [warn] Could not find existing case")
            case_id = None
    else:
        case_id = case_result["id"]
        print(f"  [ok]   Case: {case_id}")

    if not case_id:
        print("  [FAIL] No case ID — aborting")
        sys.exit(1)

    # 7. Upload documents
    print("\n[7] Uploading documents")
    existing_docs = _request("GET", f"/cases/{case_id}/documents", token=alice_token)
    existing_names = {d["original_filename"] for d in existing_docs.get("documents", [])}

    if "vendor_contract.txt" not in existing_names:
        doc1 = _multipart_upload(
            f"/cases/{case_id}/documents",
            alice_token,
            "vendor_contract.txt",
            VENDOR_CONTRACT,
        )
        print(f"  [ok]   vendor_contract.txt — id: {doc1.get('id', '?')}, status: {doc1.get('status', '?')}")
    else:
        print("  [skip] vendor_contract.txt already uploaded")

    if "amendment_001.txt" not in existing_names:
        doc2 = _multipart_upload(
            f"/cases/{case_id}/documents",
            alice_token,
            "amendment_001.txt",
            AMENDMENT_001,
        )
        print(f"  [ok]   amendment_001.txt — id: {doc2.get('id', '?')}, status: {doc2.get('status', '?')}")
    else:
        print("  [skip] amendment_001.txt already uploaded")

    # 8. Generate embeddings (admin)
    print("\n[8] Generating embeddings (ADMIN)")
    try:
        embed_result = _request("POST", "/search/embed", token=admin_token)
        print(f"  [ok]   Embedded {embed_result.get('embedded', 0)} chunks")
    except RuntimeError as exc:
        if "403" in str(exc) or "401" in str(exc):
            print("  [warn] Admin token not authorized — ADMIN promotion may not have worked")
            print("         Run: UPDATE users SET role='ADMIN' WHERE email='admin@firm.com';")
            print("         Then re-run this script")
        else:
            print(f"  [warn] Embedding failed: {exc}")

    # 9. Summary
    print()
    print("=== Seed complete ===")
    print()
    print("ALICE_TOKEN='" + alice_token + "'")
    print(f"CASE_ID='{case_id}'")
    print()
    print("Next steps:")
    print(f"  Search:    curl -s -X POST {BASE_URL}/search \\")
    print("               -H 'Authorization: Bearer $ALICE_TOKEN' \\")
    print("               -H 'Content-Type: application/json' \\")
    print(f"               -d '{{\"query\": \"payment terms\", \"case_id\": \"{case_id}\", \"limit\": 5}}'")
    print()
    print(f"  Timeline:  curl -s -X POST {BASE_URL}/cases/{case_id}/timeline/analyze \\")
    print("               -H 'Authorization: Bearer $ALICE_TOKEN' \\")
    print("               -H 'Content-Type: application/json' \\")
    print("               -d '{\"max_documents\": 5, \"force_reanalyze\": false}'")
    print()
    print("  (Timeline requires LLM_API_KEY to be set in backend .env)")


if __name__ == "__main__":
    main()
