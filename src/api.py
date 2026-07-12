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
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from langgraph.types import Command
from pydantic import BaseModel, Field

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
        return ChatResponse(
            thread_id=thread_id,
            status="awaiting_approval",
            borrador=datos.get("borrador"),
            veredicto=datos.get("veredicto"),
            mensaje=datos.get("mensaje", "¿Apruebas el material? (si/no)"),
        )
    return ChatResponse(
        thread_id=thread_id,
        status="completed",
        respuesta=estado.get("respuesta_final") or estado.get("borrador"),
    )


@app.get("/api/v1/health")
def health():
    return {
        "status": "ok",
        "service": "asistente-ia-educacion",
        "openai_configured": bool(os.getenv("OPENAI_API_KEY")),
    }


@app.post("/api/v1/chat", response_model=ChatResponse)
def chat(body: ChatRequest):
    thread_id = body.thread_id or str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    try:
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
    from src.ingestion.pipeline import ingestar

    try:
        resultado = ingestar(persistir=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Error en ingesta: {exc}") from exc
    return {
        "status": "ok",
        "indices": {nombre: len(chunks) for nombre, chunks in resultado.items()},
    }
