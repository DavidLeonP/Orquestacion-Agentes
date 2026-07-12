"""Caso de prueba pytest del pipeline API (smoke + opcional full)."""

import uuid

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.db.models import User
from src.db.session import SessionLocal


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def temp_user():
    email = f"pytest_{uuid.uuid4().hex[:8]}@pipeline.test"
    password = "PytestPass123!"
    yield email, password
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.email == email).first()
        if u:
            db.delete(u)
            db.commit()
    finally:
        db.close()


def test_caso_auth_y_conocimiento_pending(client, temp_user):
    """Caso: registro → login → crear documento pending → listar."""
    email, password = temp_user

    assert client.get("/health").status_code == 200

    r = client.post(
        "/auth/register",
        json={"email": email, "password": password, "rol": "docente"},
    )
    assert r.status_code == 201, r.text
    user_id = r.json()["id"]

    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    r = client.get("/auth/me", headers=headers)
    assert r.status_code == 200
    assert r.json()["id"] == user_id
    assert r.json()["rol"] == "docente"

    r = client.post(
        "/knowledge/apuntes/documents",
        headers=headers,
        json={
            "filename": "pytest_ohm.txt",
            "content_text": "Ley de Ohm: V = I * R. Ejemplo 12V / 6ohm = 2A.",
        },
    )
    assert r.status_code == 201
    doc = r.json()
    assert doc["status"] == "pending"
    assert doc["user_id"] == user_id
    assert doc["indice"] == "apuntes"

    r = client.get("/knowledge/documents", headers=headers)
    assert r.status_code == 200
    assert any(d["id"] == doc["id"] for d in r.json())

    # Aislamiento: sin token no hay acceso
    assert client.get("/knowledge/documents").status_code == 401
