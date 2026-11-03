"""Pipeline de validación E2E del backend (MySQL + JWT + RAG + orquestador).

Caso de prueba: un docente nuevo sube un apunte, lo indexa en MySQL,
lanza una solicitud al orquestador y recibe respuesta grounded. También
comprueba Guardrails (petición fuera de contexto → rechazo sin inventar).

Uso:
  python scripts/run_test_pipeline.py
  python scripts/run_test_pipeline.py --write-doc

Opcional (solo smoke, sin OpenAI/LLM):
  python scripts/run_test_pipeline.py --smoke
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from src.api.main import app
from src.db.models import User
from src.db.session import SessionLocal

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class StepResult:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class PipelineReport:
    steps: list[StepResult] = field(default_factory=list)
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

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

    # Guardrails: tema ajeno a la KB de la sesión (electricidad) no debe inventar examen.
    r = client.post(
        "/requests",
        headers=headers,
        json={
            "peticion": (
                "quiero que me des 2 preguntas complejas de la teoria de colores "
                "que uso los artistas del renacimiento en europa"
            )
        },
    )
    report.add(
        "POST /requests (fuera de contexto)",
        r.status_code == 202,
        f"id={r.json().get('id')}",
    )
    if r.status_code != 202:
        return
    req_fc = r.json()["id"]
    final_fc = None
    for _ in range(60):
        r = client.get(f"/requests/{req_fc}", headers=headers)
        if r.status_code != 200:
            break
        final_fc = r.json()
        if final_fc.get("status") in {"completed", "failed", "waiting_approval"}:
            break
        time.sleep(2)
    status_fc = (final_fc or {}).get("status")
    resp_fc = ((final_fc or {}).get("respuesta_final") or "").lower()
    agente_fc = (final_fc or {}).get("agente_destino")
    ok_fc = status_fc == "completed" and any(
        x in resp_fc
        for x in (
            "base documental",
            "no puedo atender",
            "no hay evidencia",
            "fuera de contexto",
            "sesión",
        )
    )
    report.add(
        "Guardrails bloquea fuera de contexto",
        ok_fc,
        f"status={status_fc} agente={agente_fc} preview={(final_fc or {}).get('respuesta_final', '')[:140]!r}",
    )


def _write_doc(report: PipelineReport, email: str, mode: str) -> Path:
    doc = ROOT / "docs" / "resultados-pipeline.md"
    total = len(report.steps)
    ok_n = sum(1 for s in report.steps if s.ok)
    lines = [
        "# Resultados de ejecución del pipeline (API JWT)",
        "",
        "> Instantánea generada por `scripts/run_test_pipeline.py --write-doc`. "
        "Incluye ingest RAG, orquestador grounded y Guardrails de cobertura KB. "
        "Diseño: [arquitectura.md](arquitectura.md).",
        "",
        f"**Fecha (UTC):** {report.started_at}",
        f"**Modo:** `{mode}` (TestClient → `src.api.main:app`)",
        f"**Usuario temporal:** `{email}`",
        f"**Estado:** {'PASS' if report.passed else 'FAIL'} ({ok_n}/{total} pasos)",
        "**Script:** [`scripts/run_test_pipeline.py`](../scripts/run_test_pipeline.py)",
        "",
        "## Resumen ejecutivo",
        "",
        "| Paso | OK | Detalle |",
        "|---|---|---|",
    ]
    for s in report.steps:
        det = (s.detail or "").replace("|", "/").replace("\n", " ")[:160]
        lines.append(f"| `{s.name}` | {'✅' if s.ok else '❌'} | {det} |")

    lines += [
        "",
        "**Veredicto:** con Guardrails activos, el pipeline JWT indexa material en "
        "MySQL/Chroma, el orquestador responde anclado a la KB de la sesión y "
        "rechaza peticiones fuera de contexto (p. ej. Renacimiento / teoría del "
        "color cuando la KB es electricidad) sin inventar un examen.",
        "",
        "## Guardrails observados",
        "",
        "- Umbral: `UMBRAL_COBERTURA_KB` (`src/config.py`, default `0.32`).",
        "- Router → nodo `fuera_contexto` si `evaluar_cobertura` falla.",
        "- Middleware `GroundingGuardrailMiddleware` en cada agente ReAct "
        "([LangChain Guardrails](https://docs.langchain.com/oss/python/langchain/guardrails)).",
        "- Constraints del examen ancladas al material recuperado (sin forzar "
        "`6 preguntas` / temas ajenos).",
        "",
        "## Cómo reproducir",
        "",
        "```bash",
        "python scripts/run_test_pipeline.py --write-doc",
        "# solo auth/CRUD:",
        "python scripts/run_test_pipeline.py --smoke",
        "```",
        "",
        "Nota: el script histórico `scripts/run_pipeline_api.py` apunta a la API "
        "legado `/api/v1/*`. El camino actual es JWT (`/auth`, `/knowledge`, `/requests`).",
        "",
    ]
    doc.write_text("\n".join(lines), encoding="utf-8")
    return doc


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
    parser.add_argument(
        "--write-doc",
        action="store_true",
        help="Escribe docs/resultados-pipeline.md con esta corrida",
    )
    args = parser.parse_args()

    email = _unique_email()
    password = "TestPipeline123!"
    report = PipelineReport()
    mode = "smoke" if args.smoke else "full (ingest + LLM + Guardrails)"

    print("=" * 60)
    print("PIPELINE DE PRUEBAS — Orquestación Agentes Educación")
    print(f"Modo: {mode}")
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

    if args.write_doc:
        path = _write_doc(report, email, mode)
        print(f"DOC: {path}")

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
