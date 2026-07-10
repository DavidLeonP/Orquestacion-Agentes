"""Pipeline de validación E2E del backend (MySQL + JWT + RAG + orquestador).

Caso de prueba: un docente nuevo sube un apunte, lo indexa en MySQL,
lanza una solicitud al orquestador y recibe respuesta grounded.

Uso:
  $env:PYTHONPATH = (Get-Location).Path
  python scripts/run_test_pipeline.py

Opcional (solo smoke, sin OpenAI/LLM):
  python scripts/run_test_pipeline.py --smoke
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from dataclasses import dataclass, field

from fastapi.testclient import TestClient

from src.api.main import app
from src.db.models import Chunk, Document, Request, User
from src.db.session import SessionLocal


@dataclass
class StepResult:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class PipelineReport:
    steps: list[StepResult] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.steps.append(StepResult(name, ok, detail))
        mark = "OK" if ok else "FAIL"
        print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))

    @property
    def passed(self) -> bool:
        return bool(self.steps) and all(s.ok for s in self.steps)


def _unique_email() -> str:
    return f"test_{uuid.uuid4().hex[:10]}@pipeline.test"


def _cleanup_user(email: str) -> None:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if user:
            db.delete(user)
            db.commit()
    finally:
        db.close()


def run_smoke(client: TestClient, report: PipelineReport, email: str, password: str) -> str | None:
    """Auth + CRUD documento (sin embeddings ni LLM)."""
    r = client.get("/health")
    report.add("GET /health", r.status_code == 200, r.text)

    r = client.post(
        "/auth/register",
        json={"email": email, "password": password, "rol": "docente"},
    )
    report.add("POST /auth/register", r.status_code == 201, f"id={r.json().get('id')}")
    if r.status_code != 201:
        return None

    r = client.post("/auth/login", json={"email": email, "password": password})
    ok = r.status_code == 200 and "access_token" in r.json()
    report.add("POST /auth/login", ok)
    if not ok:
        return None
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    r = client.get("/auth/me", headers=headers)
    report.add(
        "GET /auth/me",
        r.status_code == 200 and r.json().get("email") == email,
        r.json().get("rol", ""),
    )

    contenido = (
        "---\nasignatura: Tecnología\ncurso: 3º ESO\nanio: 2024\ntipo: apuntes\n---\n\n"
        "La ley de Ohm: V = I · R. Ejemplo: 12 V y 6 Ω → I = 2 A.\n"
    )
    r = client.post(
        "/knowledge/apuntes/documents",
        headers=headers,
        json={
            "filename": "pipeline_ohm.txt",
            "content_text": contenido,
            "metadatos": {"fuente": "pipeline_ohm.txt"},
        },
    )
    report.add("POST /knowledge/apuntes/documents", r.status_code == 201, f"doc={r.json().get('id')}")
    if r.status_code != 201:
        return token
    doc_id = r.json()["id"]

    r = client.get("/knowledge/documents", headers=headers)
    docs = r.json() if r.status_code == 200 else []
    report.add(
        "GET /knowledge/documents",
        r.status_code == 200 and any(d["id"] == doc_id for d in docs),
        f"n={len(docs)}",
    )

    r = client.patch(
        f"/knowledge/documents/{doc_id}",
        headers=headers,
        json={"content_text": contenido + "\nPotencia: P = V · I.\n"},
    )
    report.add(
        "PATCH /knowledge/documents/{id}",
        r.status_code == 200 and r.json().get("status") == "pending",
        r.json().get("status", ""),
    )

    return token


def run_full(client: TestClient, report: PipelineReport, email: str, password: str) -> None:
    """Smoke + ingest MySQL + solicitud orquestador."""
    token = run_smoke(client, report, email, password)
    if not token:
        return
    headers = {"Authorization": f"Bearer {token}"}

    r = client.post("/knowledge/ingest", headers=headers)
    body = r.json() if r.status_code == 200 else {}
    report.add(
        "POST /knowledge/ingest",
        r.status_code == 200 and body.get("procesados", 0) >= 1 and body.get("errores", 0) == 0,
        str(body),
    )

    r = client.get("/knowledge/chunks", headers=headers)
    chunks = r.json() if r.status_code == 200 else []
    report.add(
        "GET /knowledge/chunks (RAG MySQL)",
        r.status_code == 200 and len(chunks) >= 1,
        f"n={len(chunks)}",
    )

    r = client.post(
        "/requests",
        headers=headers,
        json={"peticion": "Explica brevemente la ley de Ohm usando los apuntes"},
    )
    report.add("POST /requests", r.status_code == 202, f"id={r.json().get('id')} status={r.json().get('status')}")
    if r.status_code != 202:
        return
    req_id = r.json()["id"]

    # BackgroundTasks de TestClient ya disparó la ejecución; poll por si acaso
    final = None
    for _ in range(60):
        r = client.get(f"/requests/{req_id}", headers=headers)
        if r.status_code != 200:
            break
        final = r.json()
        if final.get("status") in {"completed", "failed", "waiting_approval"}:
            break
        time.sleep(2)

    status = (final or {}).get("status")
    respuesta = (final or {}).get("respuesta_final") or ""
    error = (final or {}).get("error")
    ok = status == "completed" and len(respuesta) > 50
    detail = f"status={status} len={len(respuesta)}"
    if error:
        detail += f" error={error[:200]}"
    report.add("Orquestador responde (GET /requests/{id})", ok, detail)

    if ok:
        grounded = any(
            x in respuesta.lower()
            for x in ("ohm", "volt", "resist", "corriente", "fuente", "apuntes")
        )
        report.add("Respuesta parece grounded en KB", grounded, respuesta[:120].replace("\n", " "))

    r = client.get(f"/requests/{req_id}/events", headers=headers)
    events = r.json() if r.status_code == 200 else []
    report.add(
        "GET /requests/{id}/events",
        r.status_code == 200 and len(events) >= 1,
        f"n={len(events)}",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Pipeline de pruebas del backend")
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Solo auth + CRUD documentos (sin OpenAI/LLM)",
    )
    parser.add_argument(
        "--keep-user",
        action="store_true",
        help="No borrar el usuario de prueba al final",
    )
    args = parser.parse_args()

    email = _unique_email()
    password = "TestPipeline123!"
    report = PipelineReport()

    print("=" * 60)
    print("PIPELINE DE PRUEBAS — Orquestación Agentes Educación")
    print(f"Modo: {'smoke' if args.smoke else 'full (ingest + LLM)'}")
    print(f"Usuario temporal: {email}")
    print("=" * 60)

    try:
        with TestClient(app) as client:
            if args.smoke:
                run_smoke(client, report, email, password)
            else:
                run_full(client, report, email, password)
    except Exception as exc:  # noqa: BLE001
        report.add("Excepción no controlada", False, str(exc))
    finally:
        if not args.keep_user:
            _cleanup_user(email)
            # Verificar limpieza
            db = SessionLocal()
            try:
                left = db.query(User).filter(User.email == email).first()
                report.add("Cleanup usuario de prueba", left is None)
            finally:
                db.close()

    print("=" * 60)
    total = len(report.steps)
    ok_n = sum(1 for s in report.steps if s.ok)
    print(f"Resultado: {ok_n}/{total} pasos OK")
    if report.passed:
        print("PIPELINE PASSED")
        return 0
    print("PIPELINE FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
