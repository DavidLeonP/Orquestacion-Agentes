"""Tests de integración del router /sql-queries.

Los tests de aislamiento por rol (401/403) y de persistencia no requieren
LLM. El flujo end-to-end sí lo requiere (el BackgroundTask invoca el grafo
real) y se salta si no hay OPENAI_API_KEY, igual que test_sql_agent_graph.py.
"""

import os
import sqlite3
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


def _crear_usuario(client, rol: str) -> tuple[str, dict]:
    email = f"pytest_sql_{uuid.uuid4().hex[:8]}@sqlagent.test"
    password = "PytestPass123!"
    r = client.post("/auth/register", json={"email": email, "password": password, "rol": rol})
    assert r.status_code == 201, r.text
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    return email, {"Authorization": f"Bearer {token}"}


@pytest.fixture
def docente(client):
    email, headers = _crear_usuario(client, "docente")
    yield headers
    _borrar_usuario(email)


@pytest.fixture
def alumno(client):
    email, headers = _crear_usuario(client, "alumno")
    yield headers
    _borrar_usuario(email)


def _borrar_usuario(email: str) -> None:
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.email == email).first()
        if u:
            db.delete(u)
            db.commit()
    finally:
        db.close()


def test_sin_token_devuelve_401(client):
    assert client.post("/sql-queries", json={"pregunta": "hola"}).status_code == 401


def test_alumno_no_puede_consultar_bd_de_negocio(client, alumno):
    r = client.post("/sql-queries", json={"pregunta": "¿cuántos alumnos hay?"}, headers=alumno)
    assert r.status_code == 403


def test_listar_vacio_para_docente_nuevo(client, docente):
    r = client.get("/sql-queries", headers=docente)
    assert r.status_code == 200
    assert r.json() == []


def test_detalle_404_si_no_existe_o_no_es_del_usuario(client, docente):
    assert client.get("/sql-queries/999999999", headers=docente).status_code == 404
    assert client.get("/sql-queries/999999999/events", headers=docente).status_code == 404


@pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY"),
    reason="Requiere OPENAI_API_KEY para invocar el LLM del grafo",
)
def test_flujo_completo_docente_pregunta_y_recibe_respuesta(client, docente, tmp_path):
    ruta = tmp_path / "negocio.sqlite"
    con = sqlite3.connect(ruta)
    con.executescript(
        """
        CREATE TABLE alumnos (id INTEGER PRIMARY KEY, nombre TEXT);
        INSERT INTO alumnos VALUES (1, 'Ana'), (2, 'Luis'), (3, 'Marta');
        """
    )
    con.commit()
    con.close()

    r = client.post(
        "/sql-queries",
        json={
            "pregunta": "¿Cuántos alumnos hay en total?",
            "agent_db_uri": f"sqlite:///{ruta}",
        },
        headers=docente,
    )
    assert r.status_code == 202, r.text
    query_id = r.json()["id"]

    # TestClient ejecuta el BackgroundTask de forma síncrona antes de
    # devolver la respuesta del POST, así que para cuando llegamos aquí el
    # grafo ya debería haber terminado.
    r = client.get(f"/sql-queries/{query_id}", headers=docente)
    assert r.status_code == 200
    detalle = r.json()
    assert detalle["status"] == "completed", detalle
    assert detalle["respuesta_final"]

    r = client.get(f"/sql-queries/{query_id}/events", headers=docente)
    assert r.status_code == 200
    eventos = r.json()
    assert any(e["tipo"] == "completed" for e in eventos)
    assert any(e["tipo"] == "nodo_grafo" for e in eventos)

    # Aislamiento: otro docente no ve esta consulta.
    otro_email, otros_headers = _crear_usuario(client, "docente")
    try:
        assert client.get(f"/sql-queries/{query_id}", headers=otros_headers).status_code == 404
    finally:
        _borrar_usuario(otro_email)
