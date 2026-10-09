"""
Case endpoint tests.

Authorization rules under test:
  - ADMIN and LAWYER can create cases; RESTRICTED_LAWYER cannot.
  - Case creator (LAWYER) is automatically assigned OWNER membership.
  - Case list is scoped to the user's memberships.
  - Non-members receive 404 for individual case access.
  - VIEWER cannot update; MEMBER and OWNER can.
  - Delete requires ADMIN or OWNER.

SECURITY ISOLATION TEST:
  User A owns Case A; User B owns Case B.
  User A's GET /cases returns only Case A.
  User A's GET /cases/{case_b_id} returns 404.
"""
import uuid

from app.models.case_membership import CaseMemberRole
from app.models.user import UserRole
from tests.helpers import (
    add_membership,
    auth_headers,
    make_case,
    make_client,
    make_user,
)

CASES_URL = "/cases"


# ---------------------------------------------------------------------------
# Create case
# ---------------------------------------------------------------------------


def test_lawyer_can_create_case(client, db_session):
    lawyer = make_user(db_session, role=UserRole.LAWYER)
    c = make_client(db_session)

    resp = client.post(
        CASES_URL,
        json={
            "client_id": str(c.id),
            "case_number": "CASE-2026-001",
            "title": "Test v. Test",
        },
        headers=auth_headers(lawyer),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["case_number"] == "CASE-2026-001"
    assert data["status"] == "OPEN"


def test_admin_can_create_case(client, db_session):
    admin = make_user(db_session, role=UserRole.ADMIN)
    c = make_client(db_session)

    resp = client.post(
        CASES_URL,
        json={"client_id": str(c.id), "case_number": "CASE-ADMIN-001", "title": "Admin Case"},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 201


def test_restricted_lawyer_cannot_create_case(client, db_session):
    rl = make_user(db_session, role=UserRole.RESTRICTED_LAWYER)
    c = make_client(db_session)

    resp = client.post(
        CASES_URL,
        json={"client_id": str(c.id), "case_number": "CASE-RL-001", "title": "Restricted"},
        headers=auth_headers(rl),
    )
    assert resp.status_code == 403


def test_create_case_nonexistent_client_returns_404(client, db_session):
    lawyer = make_user(db_session, role=UserRole.LAWYER)

    resp = client.post(
        CASES_URL,
        json={
            "client_id": str(uuid.uuid4()),
            "case_number": "CASE-NOCLIENT",
            "title": "Ghost Case",
        },
        headers=auth_headers(lawyer),
    )
    assert resp.status_code == 404


def test_duplicate_case_number_rejected(client, db_session):
    lawyer = make_user(db_session, role=UserRole.LAWYER)
    c = make_client(db_session)

    payload = {"client_id": str(c.id), "case_number": "CASE-DUP-001", "title": "First"}
    client.post(CASES_URL, json=payload, headers=auth_headers(lawyer))
    resp = client.post(CASES_URL, json={**payload, "title": "Second"}, headers=auth_headers(lawyer))
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Auto-ownership
# ---------------------------------------------------------------------------


def test_case_creator_lawyer_becomes_owner(client, db_session):
    """LAWYER who creates a case is automatically added as OWNER."""
    lawyer = make_user(db_session, role=UserRole.LAWYER)
    c = make_client(db_session)

    resp = client.post(
        CASES_URL,
        json={"client_id": str(c.id), "case_number": "CASE-OWN-001", "title": "Owned"},
        headers=auth_headers(lawyer),
    )
    case_id = resp.json()["id"]

    members_resp = client.get(f"{CASES_URL}/{case_id}/members", headers=auth_headers(lawyer))
    assert members_resp.status_code == 200
    members = members_resp.json()
    assert len(members) == 1
    assert members[0]["user_id"] == str(lawyer.id)
    assert members[0]["role"] == "OWNER"


def test_admin_creating_case_does_not_get_membership(client, db_session):
    """ADMIN does not receive a membership record when creating a case."""
    admin = make_user(db_session, role=UserRole.ADMIN)
    c = make_client(db_session)

    resp = client.post(
        CASES_URL,
        json={"client_id": str(c.id), "case_number": "CASE-ADMOWN-001", "title": "Admin Owned"},
        headers=auth_headers(admin),
    )
    case_id = resp.json()["id"]

    members_resp = client.get(f"{CASES_URL}/{case_id}/members", headers=auth_headers(admin))
    assert members_resp.status_code == 200
    assert members_resp.json() == []


# ---------------------------------------------------------------------------
# List cases (scoped)
# ---------------------------------------------------------------------------


def test_admin_sees_all_cases(client, db_session):
    admin = make_user(db_session, role=UserRole.ADMIN)
    user_a = make_user(db_session, role=UserRole.LAWYER)
    user_b = make_user(db_session, role=UserRole.LAWYER)
    c = make_client(db_session)

    case_a = make_case(db_session, c, case_number="CASE-A-001")
    case_b = make_case(db_session, c, case_number="CASE-B-001")
    add_membership(db_session, case_a, user_a, CaseMemberRole.OWNER)
    add_membership(db_session, case_b, user_b, CaseMemberRole.OWNER)

    resp = client.get(CASES_URL, headers=auth_headers(admin))
    assert resp.status_code == 200
    numbers = [c_["case_number"] for c_ in resp.json()]
    assert "CASE-A-001" in numbers
    assert "CASE-B-001" in numbers


def test_lawyer_sees_only_own_cases(client, db_session):
    """
    SECURITY: User A's case list does not include User B's cases.
    """
    user_a = make_user(db_session, role=UserRole.LAWYER)
    user_b = make_user(db_session, role=UserRole.LAWYER)
    c = make_client(db_session)

    case_a = make_case(db_session, c, case_number="CASE-ISOLATION-A")
    case_b = make_case(db_session, c, case_number="CASE-ISOLATION-B")
    add_membership(db_session, case_a, user_a, CaseMemberRole.OWNER)
    add_membership(db_session, case_b, user_b, CaseMemberRole.OWNER)

    resp = client.get(CASES_URL, headers=auth_headers(user_a))
    assert resp.status_code == 200
    numbers = [c_["case_number"] for c_ in resp.json()]
    assert "CASE-ISOLATION-A" in numbers
    assert "CASE-ISOLATION-B" not in numbers


def test_restricted_lawyer_sees_only_own_cases(client, db_session):
    rl = make_user(db_session, role=UserRole.RESTRICTED_LAWYER)
    other = make_user(db_session, role=UserRole.LAWYER)
    c = make_client(db_session)

    case_rl = make_case(db_session, c, case_number="CASE-RL-VISIBLE")
    case_other = make_case(db_session, c, case_number="CASE-RL-HIDDEN")
    add_membership(db_session, case_rl, rl, CaseMemberRole.MEMBER)
    add_membership(db_session, case_other, other, CaseMemberRole.OWNER)

    resp = client.get(CASES_URL, headers=auth_headers(rl))
    numbers = [c_["case_number"] for c_ in resp.json()]
    assert "CASE-RL-VISIBLE" in numbers
    assert "CASE-RL-HIDDEN" not in numbers


# ---------------------------------------------------------------------------
# Get individual case (security isolation)
# ---------------------------------------------------------------------------


def test_member_can_get_case(client, db_session):
    user = make_user(db_session, role=UserRole.LAWYER)
    c = make_client(db_session)
    case = make_case(db_session, c)
    add_membership(db_session, case, user, CaseMemberRole.OWNER)

    resp = client.get(f"{CASES_URL}/{case.id}", headers=auth_headers(user))
    assert resp.status_code == 200


def test_non_member_cannot_get_case(client, db_session):
    """
    SECURITY: User A requests Case B (owned by User B).
    Expected: 404 (hides existence, not 403).
    """
    user_a = make_user(db_session, role=UserRole.LAWYER)
    user_b = make_user(db_session, role=UserRole.LAWYER)
    c = make_client(db_session)

    case_b = make_case(db_session, c, case_number="CASE-SEC-B")
    add_membership(db_session, case_b, user_b, CaseMemberRole.OWNER)

    resp = client.get(f"{CASES_URL}/{case_b.id}", headers=auth_headers(user_a))
    assert resp.status_code == 404


def test_admin_can_get_any_case(client, db_session):
    admin = make_user(db_session, role=UserRole.ADMIN)
    other_user = make_user(db_session, role=UserRole.LAWYER)
    c = make_client(db_session)
    case = make_case(db_session, c)
    add_membership(db_session, case, other_user, CaseMemberRole.OWNER)

    resp = client.get(f"{CASES_URL}/{case.id}", headers=auth_headers(admin))
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Update case
# ---------------------------------------------------------------------------


def test_owner_can_update_case(client, db_session):
    user = make_user(db_session, role=UserRole.LAWYER)
    c = make_client(db_session)
    case = make_case(db_session, c)
    add_membership(db_session, case, user, CaseMemberRole.OWNER)

    resp = client.put(
        f"{CASES_URL}/{case.id}",
        json={"title": "Updated Title"},
        headers=auth_headers(user),
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "Updated Title"


def test_member_can_update_case(client, db_session):
    user = make_user(db_session, role=UserRole.LAWYER)
    c = make_client(db_session)
    case = make_case(db_session, c)
    add_membership(db_session, case, user, CaseMemberRole.MEMBER)

    resp = client.put(
        f"{CASES_URL}/{case.id}",
        json={"status": "CLOSED"},
        headers=auth_headers(user),
    )
    assert resp.status_code == 200


def test_viewer_cannot_update_case(client, db_session):
    user = make_user(db_session, role=UserRole.LAWYER)
    c = make_client(db_session)
    case = make_case(db_session, c)
    add_membership(db_session, case, user, CaseMemberRole.VIEWER)

    resp = client.put(
        f"{CASES_URL}/{case.id}",
        json={"title": "Viewer Update Attempt"},
        headers=auth_headers(user),
    )
    assert resp.status_code == 403


def test_non_member_cannot_update_case(client, db_session):
    user_a = make_user(db_session, role=UserRole.LAWYER)
    user_b = make_user(db_session, role=UserRole.LAWYER)
    c = make_client(db_session)
    case_b = make_case(db_session, c)
    add_membership(db_session, case_b, user_b, CaseMemberRole.OWNER)

    resp = client.put(
        f"{CASES_URL}/{case_b.id}",
        json={"title": "Unauthorized Update"},
        headers=auth_headers(user_a),
    )
    assert resp.status_code == 404


def test_admin_can_update_any_case(client, db_session):
    admin = make_user(db_session, role=UserRole.ADMIN)
    c = make_client(db_session)
    case = make_case(db_session, c)

    resp = client.put(
        f"{CASES_URL}/{case.id}",
        json={"title": "Admin Updated"},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Delete case
# ---------------------------------------------------------------------------


def test_owner_can_delete_case(client, db_session):
    user = make_user(db_session, role=UserRole.LAWYER)
    c = make_client(db_session)
    case = make_case(db_session, c)
    add_membership(db_session, case, user, CaseMemberRole.OWNER)

    resp = client.delete(f"{CASES_URL}/{case.id}", headers=auth_headers(user))
    assert resp.status_code == 204


def test_admin_can_delete_any_case(client, db_session):
    admin = make_user(db_session, role=UserRole.ADMIN)
    c = make_client(db_session)
    case = make_case(db_session, c)

    resp = client.delete(f"{CASES_URL}/{case.id}", headers=auth_headers(admin))
    assert resp.status_code == 204


def test_member_cannot_delete_case(client, db_session):
    user = make_user(db_session, role=UserRole.LAWYER)
    c = make_client(db_session)
    case = make_case(db_session, c)
    add_membership(db_session, case, user, CaseMemberRole.MEMBER)

    resp = client.delete(f"{CASES_URL}/{case.id}", headers=auth_headers(user))
    assert resp.status_code == 403


def test_non_member_cannot_delete_case(client, db_session):
    user_a = make_user(db_session, role=UserRole.LAWYER)
    user_b = make_user(db_session, role=UserRole.LAWYER)
    c = make_client(db_session)
    case_b = make_case(db_session, c)
    add_membership(db_session, case_b, user_b, CaseMemberRole.OWNER)

    resp = client.delete(f"{CASES_URL}/{case_b.id}", headers=auth_headers(user_a))
    assert resp.status_code == 404
