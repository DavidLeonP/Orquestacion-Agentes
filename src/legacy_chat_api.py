"""API HTTP del Asistente IA para Educación (FastAPI).

Endpoints pensados para probar con Postman:
- POST /api/v1/chat      → inicia o continúa una petición (docente/alumno)
- POST /api/v1/approve   → aprueba/rechaza un examen (human-in-the-loop)
- POST /api/v1/ingestar  → reconstruye índices RAG
- GET  /api/v1/health    → estado del servicio
"""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from typing import Generator, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langgraph.types import Command
from pydantic import BaseModel, Field

from src.config import INDICES
from src.db.models import Document, User
from src.db.session import SessionLocal
from src.ingestion.mysql_pipeline import ingest_pendientes
from src.memory import mysql_store as mem
from src.rag.context import reset_rag_user_id, set_rag_user_id

_app_grafo = None

app = FastAPI(
    title="Asistente IA para Educación",
    description="API multi-agente (Curriculum, Exam, Rubric, Tutor) con RAG.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    peticion: str = Field(..., min_length=1, examples=["Explica la ley de Ohm"])
    rol: Literal["docente", "alumno"] = "docente"
    alumno_id: str = "anonimo"
    thread_id: str | None = Field(
        default=None,
        description="ID de sesión. Si se omite, se crea uno nuevo.",
    )


class ApproveRequest(BaseModel):
    thread_id: str
    decision: Literal["si", "no"] = "si"


class ChatResponse(BaseModel):
    thread_id: str
    status: Literal["completed", "awaiting_approval"]
    respuesta: str | None = None
    borrador: str | None = None
    veredicto: str | None = None
    mensaje: str | None = None


def _require_api_key() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(
            503,
            "Falta OPENAI_API_KEY. Configúrala en /opt/asistente-ia/.env y reinicia el contenedor.",
        )


def _resolve_legacy_user_id() -> int:
    if os.getenv("LEGACY_API_USER_ID"):
        return int(os.environ["LEGACY_API_USER_ID"])

    email = os.getenv("LEGACY_API_USER_EMAIL", "demo@instituto.local").lower()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if user is None:
            from src.api.security import hash_password

            user = User(
                email=email,
                password_hash=hash_password("legacy-api-demo"),
                rol="docente",
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        return user.id
    finally:
        db.close()


@contextmanager
def _legacy_context() -> Generator[int, None, None]:
    uid = _resolve_legacy_user_id()
    rag_token = set_rag_user_id(uid)
    mem_token = mem.set_memory_user_id(uid)
    try:
        yield uid
    finally:
        reset_rag_user_id(rag_token)
        mem.reset_memory_user_id(mem_token)


def _sync_data_folder(user_id: int) -> int:
    db = SessionLocal()
    creados = 0
    try:
        for indice, carpeta in INDICES.items():
            if not carpeta.exists():
                continue
            for ruta in sorted(carpeta.glob("*")):
                if ruta.suffix.lower() not in {".txt", ".md", ".pdf"}:
                    continue
                exists = (
                    db.query(Document)
                    .filter(
                        Document.user_id == user_id,
                        Document.indice == indice,
                        Document.filename == ruta.name,
                    )
                    .first()
                )
                if exists:
                    continue
                if ruta.suffix.lower() == ".pdf":
                    from pypdf import PdfReader

                    reader = PdfReader(str(ruta))
                    texto = "\n".join(
                        page.extract_text() or "" for page in reader.pages
                    )
                else:
                    texto = ruta.read_text(encoding="utf-8")
                db.add(
                    Document(
                        user_id=user_id,
                        indice=indice,
                        filename=ruta.name,
                        content_text=texto,
                        content_type="text/plain",
                        status="pending",
                        metadatos={"fuente": ruta.name},
                    )
                )
                creados += 1
        db.commit()
        return creados
    finally:
        db.close()


def _grafo():
    global _app_grafo
    _require_api_key()
    if _app_grafo is None:
        from src.orchestrator.graph import construir_grafo

        _app_grafo = construir_grafo()
    return _app_grafo


def _parsear_estado(estado: dict, thread_id: str) -> ChatResponse:
    if "__interrupt__" in estado:
        datos = estado["__interrupt__"][0].value
        veredicto = datos.get("veredicto")
        if isinstance(veredicto, dict):
            from src.agents.schemas import VeredictoValidacion, render_veredicto, safe_parse

            v, _ = safe_parse(VeredictoValidacion, veredicto)
            veredicto = render_veredicto(v)
        return ChatResponse(
            thread_id=thread_id,
            status="awaiting_approval",
            borrador=datos.get("borrador"),
            veredicto=veredicto if isinstance(veredicto, str) else str(veredicto),
            mensaje=datos.get("mensaje", "¿Apruebas el material? (si/no)"),
        )
    return ChatResponse(
        thread_id=thread_id,
        status="completed",
        respuesta=estado.get("respuesta_final") or estado.get("borrador"),
    )


@app.get("/api/v1/health")
def health():
    from src.llm import describe_llm

    return {
        "status": "ok",
        "service": "asistente-ia-educacion",
        "openai_configured": bool(os.getenv("OPENAI_API_KEY")),
        "llm": describe_llm(),
    }


@app.post("/api/v1/chat", response_model=ChatResponse)
def chat(body: ChatRequest):
    thread_id = body.thread_id or str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    try:
        with _legacy_context():
            estado = _grafo().invoke(
                {
                    "peticion": body.peticion,
                    "rol_usuario": body.rol,
                    "alumno_id": body.alumno_id,
                },
                config=config,
            )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Error al procesar la petición: {exc}") from exc
    return _parsear_estado(estado, thread_id)


@app.post("/api/v1/approve", response_model=ChatResponse)
def approve(body: ApproveRequest):
    config = {"configurable": {"thread_id": body.thread_id}}
    try:
        with _legacy_context():
            estado = _grafo().invoke(Command(resume=body.decision), config=config)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            400,
            f"No se pudo reanudar el thread (¿thread_id inválido o sin aprobación pendiente?): {exc}",
        ) from exc
    return _parsear_estado(estado, body.thread_id)


@app.post("/api/v1/ingestar")
def ingestar_docs():
    _require_api_key()
    try:
        with _legacy_context() as user_id:
            nuevos = _sync_data_folder(user_id)
            db = SessionLocal()
            try:
                resultado = ingest_pendientes(db, user_id)
            finally:
                db.close()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Error en ingesta: {exc}") from exc
    return {
        "status": "ok",
        "documentos_nuevos": nuevos,
        "indices": {
            item["filename"]: item.get("chunks", 0)
            for item in resultado.get("detalle", [])
            if "chunks" in item
        },
        "ingest": resultado,
    }
