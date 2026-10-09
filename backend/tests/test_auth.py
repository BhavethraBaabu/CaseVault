"""
Authentication endpoint tests.

All tests use the `client` fixture (SQLite in-memory, no PostgreSQL needed).
"""
from datetime import timedelta
from unittest.mock import patch

import pytest

from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User, UserRole

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REGISTER_URL = "/auth/register"
LOGIN_URL = "/auth/login"
ME_URL = "/auth/me"
LOGOUT_URL = "/auth/logout"

VALID_USER = {
    "email": "lawyer@example.com",
    "password": "SecurePass123!",
    "full_name": "Jane Lawyer",
}


def register_and_login(client) -> str:
    """Register a user and return their access token."""
    client.post(REGISTER_URL, json=VALID_USER)
    creds = {"email": VALID_USER["email"], "password": VALID_USER["password"]}
    resp = client.post(LOGIN_URL, json=creds)
    return resp.json()["access_token"]


# ---------------------------------------------------------------------------
# Password hashing unit tests
# ---------------------------------------------------------------------------


def test_password_is_hashed():
    hashed = hash_password("plaintext")
    assert hashed != "plaintext"
    assert hashed.startswith("$2")  # bcrypt prefix


def test_password_verify_correct():
    hashed = hash_password("correct")
    assert verify_password("correct", hashed) is True


def test_password_verify_wrong():
    hashed = hash_password("correct")
    assert verify_password("wrong", hashed) is False


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------


def test_register_success(client):
    resp = client.post(REGISTER_URL, json=VALID_USER)
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == VALID_USER["email"]
    assert data["full_name"] == VALID_USER["full_name"]
    assert data["role"] == UserRole.LAWYER
    assert data["is_active"] is True
    assert "id" in data
    # Crucially: password_hash must never be returned
    assert "password_hash" not in data
    assert "password" not in data


def test_register_duplicate_email(client):
    client.post(REGISTER_URL, json=VALID_USER)
    resp = client.post(REGISTER_URL, json=VALID_USER)
    assert resp.status_code == 409
    assert "already exists" in resp.json()["detail"]


def test_register_short_password(client):
    payload = {**VALID_USER, "password": "short"}
    resp = client.post(REGISTER_URL, json=payload)
    assert resp.status_code == 422


def test_register_empty_full_name(client):
    payload = {**VALID_USER, "full_name": "   "}
    resp = client.post(REGISTER_URL, json=payload)
    assert resp.status_code == 422


def test_register_email_normalised(client):
    payload = {**VALID_USER, "email": "  LAWYER@EXAMPLE.COM  "}
    resp = client.post(REGISTER_URL, json=payload)
    assert resp.status_code == 201
    assert resp.json()["email"] == "lawyer@example.com"


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


def test_login_success(client):
    client.post(REGISTER_URL, json=VALID_USER)
    creds = {"email": VALID_USER["email"], "password": VALID_USER["password"]}
    resp = client.post(LOGIN_URL, json=creds)
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_login_wrong_password(client):
    client.post(REGISTER_URL, json=VALID_USER)
    resp = client.post(LOGIN_URL, json={"email": VALID_USER["email"], "password": "wrongpassword"})
    assert resp.status_code == 401


def test_login_unknown_email(client):
    resp = client.post(LOGIN_URL, json={"email": "nobody@example.com", "password": "anything"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# /auth/me
# ---------------------------------------------------------------------------


def test_me_requires_authentication(client):
    resp = client.get(ME_URL)
    assert resp.status_code == 403  # HTTPBearer returns 403 when no header present


def test_me_with_valid_token(client):
    token = register_and_login(client)
    resp = client.get(ME_URL, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == VALID_USER["email"]
    assert "password_hash" not in data


def test_me_with_invalid_token(client):
    resp = client.get(ME_URL, headers={"Authorization": "Bearer notavalidtoken"})
    assert resp.status_code == 401


def test_me_with_expired_token(client):
    client.post(REGISTER_URL, json=VALID_USER)
    # Create a token that expired 1 second in the past

    with patch("app.core.security.timedelta") as mock_td:
        mock_td.return_value = timedelta(seconds=-1)
        expired_token = create_access_token(
            subject="00000000-0000-0000-0000-000000000001",
            role=UserRole.LAWYER,
            expires_delta=timedelta(seconds=-1),
        )
    resp = client.get(ME_URL, headers={"Authorization": f"Bearer {expired_token}"})
    assert resp.status_code == 401


def test_me_inactive_user(client, db_session):
    token = register_and_login(client)
    # Deactivate the user directly in the test DB
    user = db_session.query(User).filter_by(email=VALID_USER["email"]).first()
    user.is_active = False
    db_session.commit()

    resp = client.get(ME_URL, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Role authorization
# ---------------------------------------------------------------------------


def test_require_role_blocks_wrong_role(db_session):
    """require_role(ADMIN) must raise 403 when user role is LAWYER."""
    import uuid

    from fastapi import HTTPException

    from app.api.deps import require_role

    user = User(
        id=uuid.uuid4(),
        email="admin-test@example.com",
        password_hash="hashed",
        full_name="Role Test",
        role=UserRole.LAWYER,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    dependency = require_role(UserRole.ADMIN)
    with pytest.raises(HTTPException) as exc_info:
        dependency(user)
    assert exc_info.value.status_code == 403


def test_require_role_allows_correct_role(db_session):
    """require_role(LAWYER) must return the user when role is LAWYER."""
    import uuid

    from app.api.deps import require_role

    user = User(
        id=uuid.uuid4(),
        email="role-ok@example.com",
        password_hash="hashed",
        full_name="Role OK",
        role=UserRole.LAWYER,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    dependency = require_role(UserRole.LAWYER)
    result = dependency(user)
    assert result == user


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


def test_logout_returns_200(client):
    resp = client.post(LOGOUT_URL)
    assert resp.status_code == 200
    assert "message" in resp.json()
