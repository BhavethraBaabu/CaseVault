"""
Case membership endpoint tests.

Authorization rules under test:
  - OWNER (and ADMIN) can add, change, or remove members.
  - MEMBER and VIEWER cannot manage membership.
  - Non-members cannot see or manage membership.
  - Duplicate memberships are rejected with 409.
  - Removing the last OWNER is rejected with 400.
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


def members_url(case_id) -> str:
    return f"{CASES_URL}/{case_id}/members"


# ---------------------------------------------------------------------------
# Add member
# ---------------------------------------------------------------------------


def test_owner_can_add_member(client, db_session):
    owner = make_user(db_session, role=UserRole.LAWYER)
    new_member = make_user(db_session, role=UserRole.LAWYER)
    c = make_client(db_session)
    case = make_case(db_session, c)
    add_membership(db_session, case, owner, CaseMemberRole.OWNER)

    resp = client.post(
        members_url(case.id),
        json={"user_id": str(new_member.id), "role": "MEMBER"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["user_id"] == str(new_member.id)
    assert data["role"] == "MEMBER"


def test_admin_can_add_member(client, db_session):
    admin = make_user(db_session, role=UserRole.ADMIN)
    target = make_user(db_session, role=UserRole.LAWYER)
    c = make_client(db_session)
    case = make_case(db_session, c)

    resp = client.post(
        members_url(case.id),
        json={"user_id": str(target.id), "role": "VIEWER"},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 201


def test_member_cannot_add_member(client, db_session):
    member_user = make_user(db_session, role=UserRole.LAWYER)
    new_user = make_user(db_session, role=UserRole.LAWYER)
    c = make_client(db_session)
    case = make_case(db_session, c)
    add_membership(db_session, case, member_user, CaseMemberRole.MEMBER)

    resp = client.post(
        members_url(case.id),
        json={"user_id": str(new_user.id), "role": "VIEWER"},
        headers=auth_headers(member_user),
    )
    assert resp.status_code == 403


def test_viewer_cannot_add_member(client, db_session):
    viewer = make_user(db_session, role=UserRole.LAWYER)
    new_user = make_user(db_session, role=UserRole.LAWYER)
    c = make_client(db_session)
    case = make_case(db_session, c)
    add_membership(db_session, case, viewer, CaseMemberRole.VIEWER)

    resp = client.post(
        members_url(case.id),
        json={"user_id": str(new_user.id), "role": "VIEWER"},
        headers=auth_headers(viewer),
    )
    assert resp.status_code == 403


def test_non_member_cannot_add_member(client, db_session):
    non_member = make_user(db_session, role=UserRole.LAWYER)
    target = make_user(db_session, role=UserRole.LAWYER)
    c = make_client(db_session)
    case = make_case(db_session, c)

    resp = client.post(
        members_url(case.id),
        json={"user_id": str(target.id), "role": "VIEWER"},
        headers=auth_headers(non_member),
    )
    assert resp.status_code == 404


def test_duplicate_membership_rejected(client, db_session):
    owner = make_user(db_session, role=UserRole.LAWYER)
    target = make_user(db_session, role=UserRole.LAWYER)
    c = make_client(db_session)
    case = make_case(db_session, c)
    add_membership(db_session, case, owner, CaseMemberRole.OWNER)
    add_membership(db_session, case, target, CaseMemberRole.VIEWER)

    resp = client.post(
        members_url(case.id),
        json={"user_id": str(target.id), "role": "MEMBER"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 409


def test_add_nonexistent_user_returns_404(client, db_session):
    owner = make_user(db_session, role=UserRole.LAWYER)
    c = make_client(db_session)
    case = make_case(db_session, c)
    add_membership(db_session, case, owner, CaseMemberRole.OWNER)

    resp = client.post(
        members_url(case.id),
        json={"user_id": str(uuid.uuid4()), "role": "MEMBER"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# List members
# ---------------------------------------------------------------------------


def test_case_member_can_list_members(client, db_session):
    owner = make_user(db_session, role=UserRole.LAWYER)
    viewer = make_user(db_session, role=UserRole.LAWYER)
    c = make_client(db_session)
    case = make_case(db_session, c)
    add_membership(db_session, case, owner, CaseMemberRole.OWNER)
    add_membership(db_session, case, viewer, CaseMemberRole.VIEWER)

    resp = client.get(members_url(case.id), headers=auth_headers(viewer))
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_non_member_cannot_list_members(client, db_session):
    outsider = make_user(db_session, role=UserRole.LAWYER)
    c = make_client(db_session)
    case = make_case(db_session, c)

    resp = client.get(members_url(case.id), headers=auth_headers(outsider))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Change member role
# ---------------------------------------------------------------------------


def test_owner_can_change_member_role(client, db_session):
    owner = make_user(db_session, role=UserRole.LAWYER)
    target = make_user(db_session, role=UserRole.LAWYER)
    c = make_client(db_session)
    case = make_case(db_session, c)
    add_membership(db_session, case, owner, CaseMemberRole.OWNER)
    add_membership(db_session, case, target, CaseMemberRole.VIEWER)

    resp = client.put(
        f"{CASES_URL}/{case.id}/members/{target.id}",
        json={"role": "MEMBER"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "MEMBER"


def test_member_cannot_change_roles(client, db_session):
    member_user = make_user(db_session, role=UserRole.LAWYER)
    target = make_user(db_session, role=UserRole.LAWYER)
    c = make_client(db_session)
    case = make_case(db_session, c)
    add_membership(db_session, case, member_user, CaseMemberRole.MEMBER)
    add_membership(db_session, case, target, CaseMemberRole.VIEWER)

    resp = client.put(
        f"{CASES_URL}/{case.id}/members/{target.id}",
        json={"role": "MEMBER"},
        headers=auth_headers(member_user),
    )
    assert resp.status_code == 403


def test_admin_can_change_member_role(client, db_session):
    admin = make_user(db_session, role=UserRole.ADMIN)
    target = make_user(db_session, role=UserRole.LAWYER)
    c = make_client(db_session)
    case = make_case(db_session, c)
    add_membership(db_session, case, target, CaseMemberRole.VIEWER)

    resp = client.put(
        f"{CASES_URL}/{case.id}/members/{target.id}",
        json={"role": "OWNER"},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "OWNER"


# ---------------------------------------------------------------------------
# Remove member
# ---------------------------------------------------------------------------


def test_owner_can_remove_member(client, db_session):
    owner = make_user(db_session, role=UserRole.LAWYER)
    target = make_user(db_session, role=UserRole.LAWYER)
    c = make_client(db_session)
    case = make_case(db_session, c)
    add_membership(db_session, case, owner, CaseMemberRole.OWNER)
    add_membership(db_session, case, target, CaseMemberRole.MEMBER)

    resp = client.delete(
        f"{CASES_URL}/{case.id}/members/{target.id}",
        headers=auth_headers(owner),
    )
    assert resp.status_code == 204


def test_cannot_remove_last_owner(client, db_session):
    """Removing the sole OWNER must be rejected."""
    owner = make_user(db_session, role=UserRole.LAWYER)
    c = make_client(db_session)
    case = make_case(db_session, c)
    add_membership(db_session, case, owner, CaseMemberRole.OWNER)

    resp = client.delete(
        f"{CASES_URL}/{case.id}/members/{owner.id}",
        headers=auth_headers(owner),
    )
    assert resp.status_code == 400
    assert "last owner" in resp.json()["detail"].lower()


def test_can_remove_owner_when_another_owner_exists(client, db_session):
    owner1 = make_user(db_session, role=UserRole.LAWYER)
    owner2 = make_user(db_session, role=UserRole.LAWYER)
    c = make_client(db_session)
    case = make_case(db_session, c)
    add_membership(db_session, case, owner1, CaseMemberRole.OWNER)
    add_membership(db_session, case, owner2, CaseMemberRole.OWNER)

    resp = client.delete(
        f"{CASES_URL}/{case.id}/members/{owner1.id}",
        headers=auth_headers(owner2),
    )
    assert resp.status_code == 204


def test_member_cannot_remove_members(client, db_session):
    member_user = make_user(db_session, role=UserRole.LAWYER)
    target = make_user(db_session, role=UserRole.LAWYER)
    c = make_client(db_session)
    case = make_case(db_session, c)
    add_membership(db_session, case, member_user, CaseMemberRole.MEMBER)
    add_membership(db_session, case, target, CaseMemberRole.VIEWER)

    resp = client.delete(
        f"{CASES_URL}/{case.id}/members/{target.id}",
        headers=auth_headers(member_user),
    )
    assert resp.status_code == 403


def test_admin_can_remove_member(client, db_session):
    admin = make_user(db_session, role=UserRole.ADMIN)
    target = make_user(db_session, role=UserRole.LAWYER)
    owner = make_user(db_session, role=UserRole.LAWYER)
    c = make_client(db_session)
    case = make_case(db_session, c)
    add_membership(db_session, case, owner, CaseMemberRole.OWNER)
    add_membership(db_session, case, target, CaseMemberRole.MEMBER)

    resp = client.delete(
        f"{CASES_URL}/{case.id}/members/{target.id}",
        headers=auth_headers(admin),
    )
    assert resp.status_code == 204
