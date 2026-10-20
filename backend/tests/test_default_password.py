"""An account on the default password must change it before using the API."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.core.config import DEFAULT_ADMIN_PASSWORD, settings
from app.core.database import Base, get_db
from app.core.security import PASSWORD_CHANGE_REQUIRED, generate_token, hash_password, hash_token
from app.main import app
from app.models.api_token import ApiToken
from app.models.user import User


@pytest.fixture
def db(monkeypatch: pytest.MonkeyPatch) -> Iterator[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(main, "SessionLocal", factory)
    session = factory()
    app.dependency_overrides[get_db] = lambda: session
    try:
        yield session
    finally:
        app.dependency_overrides.clear()
        session.close()


def _login(client: TestClient, password: str) -> dict:
    response = client.post("/api/auth/login", json={"username": "admin", "password": password})
    assert response.status_code == 200
    return response.json()


def test_bootstrap_admin_on_the_default_password_is_flagged(db: Session) -> None:
    main._seed_admin()
    assert db.scalar(select(User)).must_change_password is True


def test_bootstrap_admin_with_its_own_password_is_not(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "admin_password", "s3cret-from-env")
    main._seed_admin()
    assert db.scalar(select(User)).must_change_password is False


def test_api_is_closed_until_the_password_changes(db: Session) -> None:
    main._seed_admin()
    client = TestClient(app)

    assert _login(client, DEFAULT_ADMIN_PASSWORD)["must_change_password"] is True
    # The UI still learns who is signed in, and why it is blocked.
    assert client.get("/api/auth/me").json()["must_change_password"] is True
    refused = client.get("/api/tokens")
    assert refused.status_code == 403 and refused.json()["detail"] == PASSWORD_CHANGE_REQUIRED

    same = client.post(
        "/api/auth/password",
        json={"current_password": "admin", "new_password": "admin"},
    )
    assert same.status_code == 422  # "admin" is under the 6-character minimum anyway
    changed = client.post(
        "/api/auth/password",
        json={"current_password": "admin", "new_password": "a-real-password"},
    )
    assert changed.status_code == 204

    assert client.get("/api/auth/me").json()["must_change_password"] is False
    assert client.get("/api/tokens").status_code == 200


def test_new_password_must_differ(db: Session) -> None:
    db.add(User(username="admin", hashed_password=hash_password("longpassword"), is_admin=True))
    db.commit()
    client = TestClient(app)
    _login(client, "longpassword")

    response = client.post(
        "/api/auth/password",
        json={"current_password": "longpassword", "new_password": "longpassword"},
    )
    assert response.status_code == 400


def test_older_installs_are_flagged_at_login(db: Session) -> None:
    # Created before the flag existed: still on "admin", but not marked.
    db.add(User(username="admin", hashed_password=hash_password("admin"), is_admin=True))
    db.commit()
    client = TestClient(app)

    assert _login(client, "admin")["must_change_password"] is True
    assert client.get("/api/tokens").status_code == 403


def test_a_token_does_not_bypass_the_change(db: Session) -> None:
    main._seed_admin()
    admin = db.scalar(select(User))
    token = generate_token()
    db.add(ApiToken(user_id=admin.id, name="ci", prefix=token[:10], token_hash=hash_token(token)))
    db.commit()

    response = TestClient(app).get("/api/tokens", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403
