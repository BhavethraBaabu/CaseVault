"""
Test configuration using SQLite in-memory database.

Each test gets a fresh, isolated database — no PostgreSQL required.
The get_db dependency is overridden for every test via the `client` fixture.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 — must be imported before Base.metadata.create_all
from app.api.deps import get_db
from app.db.session import Base
from app.main import app as fastapi_app

TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture
def db_session():
    """Fresh SQLite in-memory DB per test — rolled back on teardown."""
    # StaticPool ensures all engine.connect() calls share ONE underlying connection,
    # so the in-memory SQLite database persists across the session lifecycle.
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestSessionLocal()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def client(db_session):
    """TestClient with get_db overridden to use the in-memory SQLite session."""

    def _override_get_db():
        yield db_session

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    with TestClient(fastapi_app) as c:
        yield c
    fastapi_app.dependency_overrides.clear()
