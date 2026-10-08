from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_ok_with_db():
    with patch("app.api.v1.health.check_db_connection", return_value=True):
        response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == "0.1.0"
    assert data["database"] == "ok"


def test_health_ok_without_db():
    with patch("app.api.v1.health.check_db_connection", return_value=False):
        response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "unavailable"


def test_health_response_shape():
    with patch("app.api.v1.health.check_db_connection", return_value=True):
        response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert set(data.keys()) == {"status", "version", "database"}


def test_app_starts():
    """Verify the application instantiates without errors."""
    assert app.title == "CaseVault"
    assert app.version == "0.1.0"
