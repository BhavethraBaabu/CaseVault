"""
Client endpoint tests.

Authorization rules under test:
  - ADMIN and LAWYER can create clients; RESTRICTED_LAWYER cannot.
  - Client visibility is scoped to the user's case memberships.
  - Unauthorized users receive 404 (not 403) for specific resource access.
  - Update requires ADMIN or case OWNER/MEMBER; RESTRICTED_LAWYER is blocked.
  - Delete is ADMIN-only; blocked if associated cases exist.
"""

from app.models.case_membership import CaseMemberRole
from app.models.user import UserRole
from tests.helpers import (
    add_membership,
    auth_headers,
    make_case,
    make_client,
    make_user,
)

CLIENTS_URL = "/clients"


# ---------------------------------------------------------------------------
# Create client
# ---------------------------------------------------------------------------


def test_lawyer_can_create_client(client, db_session):
    lawyer = make_user(db_session, role=UserRole.LAWYER)
    resp = client.post(
        CLIENTS_URL,
        json={"name": "Acme Corp", "email": "acme@example.com"},
        headers=auth_headers(lawyer),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Acme Corp"
    assert data["email"] == "acme@example.com"
    assert "id" in data


def test_admin_can_create_client(client, db_session):
    admin = make_user(db_session, role=UserRole.ADMIN)
    resp = client.post(
        CLIENTS_URL,
        json={"name": "Admin Client"},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 201


def test_restricted_lawyer_cannot_create_client(client, db_session):
    rl = make_user(db_session, role=UserRole.RESTRICTED_LAWYER)
    resp = client.post(
        CLIENTS_URL,
        json={"name": "Restricted Client"},
        headers=auth_headers(rl),
    )
    assert resp.status_code == 403


def test_unauthenticated_cannot_create_client(client):
    resp = client.post(CLIENTS_URL, json={"name": "No Auth"})
    assert resp.status_code == 403  # HTTPBearer returns 403 when no header


def test_create_client_empty_name_rejected(client, db_session):
    lawyer = make_user(db_session, role=UserRole.LAWYER)
    resp = client.post(
        CLIENTS_URL,
        json={"name": "   "},
        headers=auth_headers(lawyer),
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Get client (scoped by case membership)
# ---------------------------------------------------------------------------


def test_authorized_user_can_get_client(client, db_session):
    lawyer = make_user(db_session, role=UserRole.LAWYER)
    c = make_client(db_session, name="Visible Corp")
    case = make_case(db_session, client=c)
    add_membership(db_session, case, lawyer, CaseMemberRole.OWNER)

    resp = client.get(f"{CLIENTS_URL}/{c.id}", headers=auth_headers(lawyer))
    assert resp.status_code == 200
    assert resp.json()["name"] == "Visible Corp"


def test_unauthorized_user_cannot_get_unrelated_client(client, db_session):
    """
    SECURITY: User A cannot access Client B even when authenticated.
    The resource is hidden via 404 (not 403) to avoid leaking existence.
    """
    user_a = make_user(db_session, role=UserRole.LAWYER)
    unrelated_client = make_client(db_session, name="Other Corp")

    resp = client.get(f"{CLIENTS_URL}/{unrelated_client.id}", headers=auth_headers(user_a))
    assert resp.status_code == 404


def test_admin_can_get_any_client(client, db_session):
    admin = make_user(db_session, role=UserRole.ADMIN)
    c = make_client(db_session, name="Any Corp")

    resp = client.get(f"{CLIENTS_URL}/{c.id}", headers=auth_headers(admin))
    assert resp.status_code == 200


def test_get_nonexistent_client_returns_404(client, db_session):
    admin = make_user(db_session, role=UserRole.ADMIN)
    import uuid
    resp = client.get(f"{CLIENTS_URL}/{uuid.uuid4()}", headers=auth_headers(admin))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# List clients (scoped)
# ---------------------------------------------------------------------------


def test_client_list_scoped_to_case_memberships(client, db_session):
    """
    SECURITY: GET /clients returns only clients accessible via case membership.
    Client B (no membership for User A) must NOT appear in the list.
    """
    user_a = make_user(db_session, role=UserRole.LAWYER)

    client_a = make_client(db_session, name="Client A")
    make_client(db_session, name="Client B")  # no cases for user_a

    case_a = make_case(db_session, client=client_a)
    add_membership(db_session, case_a, user_a, CaseMemberRole.OWNER)

    resp = client.get(CLIENTS_URL, headers=auth_headers(user_a))
    assert resp.status_code == 200
    names = [c["name"] for c in resp.json()]
    assert "Client A" in names
    assert "Client B" not in names


def test_admin_sees_all_clients(client, db_session):
    admin = make_user(db_session, role=UserRole.ADMIN)
    make_client(db_session, name="Alpha")
    make_client(db_session, name="Beta")

    resp = client.get(CLIENTS_URL, headers=auth_headers(admin))
    assert resp.status_code == 200
    names = [c["name"] for c in resp.json()]
    assert "Alpha" in names
    assert "Beta" in names


def test_lawyer_with_no_cases_sees_empty_client_list(client, db_session):
    lawyer = make_user(db_session, role=UserRole.LAWYER)
    make_client(db_session, name="Unreachable Corp")

    resp = client.get(CLIENTS_URL, headers=auth_headers(lawyer))
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# Update client
# ---------------------------------------------------------------------------


def test_admin_can_update_client(client, db_session):
    admin = make_user(db_session, role=UserRole.ADMIN)
    c = make_client(db_session, name="Old Name")

    resp = client.put(
        f"{CLIENTS_URL}/{c.id}",
        json={"name": "New Name"},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "New Name"


def test_lawyer_owner_can_update_client(client, db_session):
    lawyer = make_user(db_session, role=UserRole.LAWYER)
    c = make_client(db_session, name="Old Name")
    case = make_case(db_session, client=c)
    add_membership(db_session, case, lawyer, CaseMemberRole.OWNER)

    resp = client.put(
        f"{CLIENTS_URL}/{c.id}",
        json={"name": "Updated Name"},
        headers=auth_headers(lawyer),
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated Name"


def test_lawyer_viewer_cannot_update_client(client, db_session):
    lawyer = make_user(db_session, role=UserRole.LAWYER)
    c = make_client(db_session, name="Static Corp")
    case = make_case(db_session, client=c)
    add_membership(db_session, case, lawyer, CaseMemberRole.VIEWER)

    resp = client.put(
        f"{CLIENTS_URL}/{c.id}",
        json={"name": "Should Not Update"},
        headers=auth_headers(lawyer),
    )
    assert resp.status_code == 403


def test_restricted_lawyer_cannot_update_client(client, db_session):
    rl = make_user(db_session, role=UserRole.RESTRICTED_LAWYER)
    c = make_client(db_session, name="Protected Corp")
    case = make_case(db_session, client=c)
    add_membership(db_session, case, rl, CaseMemberRole.OWNER)

    resp = client.put(
        f"{CLIENTS_URL}/{c.id}",
        json={"name": "Attempt"},
        headers=auth_headers(rl),
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Delete client
# ---------------------------------------------------------------------------


def test_admin_can_delete_client_without_cases(client, db_session):
    admin = make_user(db_session, role=UserRole.ADMIN)
    c = make_client(db_session, name="Deletable Corp")

    resp = client.delete(f"{CLIENTS_URL}/{c.id}", headers=auth_headers(admin))
    assert resp.status_code == 204


def test_cannot_delete_client_with_cases(client, db_session):
    admin = make_user(db_session, role=UserRole.ADMIN)
    c = make_client(db_session, name="Has Cases Corp")
    make_case(db_session, client=c)

    resp = client.delete(f"{CLIENTS_URL}/{c.id}", headers=auth_headers(admin))
    assert resp.status_code == 409


def test_lawyer_cannot_delete_client(client, db_session):
    lawyer = make_user(db_session, role=UserRole.LAWYER)
    c = make_client(db_session, name="Protected Corp")

    resp = client.delete(f"{CLIENTS_URL}/{c.id}", headers=auth_headers(lawyer))
    assert resp.status_code == 403
