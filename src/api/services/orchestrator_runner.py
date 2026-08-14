"""Ejecución del orquestador para la API REST."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.agents.schemas import (
    VeredictoValidacion,
    render_veredicto,
    safe_parse,
)
from src.db.models import Approval, Request, RequestEvent
from src.db.session import SessionLocal
from src.memory import mysql_store as mem
from src.orchestrator.graph import construir_grafo
from src.rag.context import reset_rag_user_id, set_rag_user_id


def _texto_veredicto_hitl(interrupt_data: dict) -> str:
    """Normaliza veredicto tipado o legado a texto para la tabla approvals."""
    raw = interrupt_data.get("veredicto", "")
    if isinstance(raw, dict):
        veredicto, _ = safe_parse(VeredictoValidacion, raw)
        return render_veredicto(veredicto)
    if isinstance(raw, str):
        return raw
    return str(raw or "")


def _borrador_hitl(interrupt_data: dict) -> str:
    return str(interrupt_data.get("borrador") or "")


def _refresh_db(db: Session, request_id: int) -> tuple[Session, Request]:
    """Reabre la sesión si MySQL cerró la conexión durante una inferencia larga."""
    try:
        db.execute(text("SELECT 1"))
        req = db.get(Request, request_id)
        if req is None:
            raise RuntimeError(f"Request {request_id} no encontrada")
        return db, req
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        try:
            db.close()
        except Exception:
            pass
        db = SessionLocal()
        req = db.get(Request, request_id)
        if req is None:
            raise RuntimeError(f"Request {request_id} no encontrada tras reconectar")
        return db, req


# Checkpointer de proceso (HITL entre requests HTTP mientras el proceso viva).
# Para multi-worker en producción conviene un checkpointer externo.
_CHECKPOINTER = MemorySaver()
_APP = None


def _app():
    global _APP
    if _APP is None:
        _APP = construir_grafo(checkpointer=_CHECKPOINTER, memory_backend=mem)
    return _APP


def _add_event(db: Session, request_id: int, tipo: str, payload: dict | None = None) -> Session:
    """Inserta evento; reconecta si MySQL cerró la sesión idle."""
    try:
        db.execute(text("SELECT 1"))
        db.add(RequestEvent(request_id=request_id, tipo=tipo, payload=payload or {}))
        db.commit()
        return db
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        try:
            db.close()
        except Exception:
            pass
        db = SessionLocal()
        db.add(RequestEvent(request_id=request_id, tipo=tipo, payload=payload or {}))
        db.commit()
        return db


def _mark_failed(request_id: int, error: str) -> None:
    db = SessionLocal()
    try:
        req = db.get(Request, request_id)
        if req is None:
            return
        req.status = "failed"
        req.error = error[:4000]
        db.commit()
        db.add(
            RequestEvent(
                request_id=request_id,
                tipo="failed",
                payload={"error": error[:500]},
            )
        )
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        try:
            db.close()
        except Exception:
            pass


def ejecutar_request(request_id: int) -> None:
    """Ejecuta el grafo hasta completar o interrupt HITL.

    Nunca propaga excepciones: el TestClient de FastAPI re-lanza errores de
    BackgroundTasks y rompería el pipeline E2E con LLMs locales lentos.
    """
    try:
        _ejecutar_request_impl(request_id)
    except Exception as exc:  # noqa: BLE001
        _mark_failed(request_id, str(exc))


def _ejecutar_request_impl(request_id: int) -> None:
    db = SessionLocal()
    rag_token = None
    mem_token = None
    try:
        req = db.get(Request, request_id)
        if req is None:
            return

        rag_token = set_rag_user_id(req.user_id)
        mem_token = mem.set_memory_user_id(req.user_id)

        app = _app()
        config = {"configurable": {"thread_id": req.thread_id}}
        entrada = {
            "peticion": req.peticion,
            "rol_usuario": req.rol,
            "alumno_id": str(req.user_id) if req.rol == "alumno" else "anonimo",
        }

        estado: dict = {}
        for chunk in app.stream(entrada, config=config, stream_mode="updates"):
            db, req = _refresh_db(db, request_id)
            if "__interrupt__" in chunk:
                interrupt_data = chunk["__interrupt__"][0].value
                req.status = "waiting_approval"
                req.agente_destino = estado.get("agente_destino") or req.agente_destino
                if req.approval is None:
                    db.add(
                        Approval(
                            request_id=req.id,
                            borrador=_borrador_hitl(interrupt_data),
                            veredicto=_texto_veredicto_hitl(interrupt_data),
                            decision="pending",
                        )
                    )
                else:
                    req.approval.borrador = _borrador_hitl(interrupt_data)
                    req.approval.veredicto = _texto_veredicto_hitl(interrupt_data)
                    req.approval.decision = "pending"
                db.commit()
                db = _add_event(
                    db,
                    req.id,
                    "waiting_approval",
                    {
                        "mensaje": interrupt_data.get("mensaje"),
                        "veredicto": interrupt_data.get("veredicto"),
                    },
                )
                return

            for nodo, actualizacion in chunk.items():
                if nodo.startswith("__") or not isinstance(actualizacion, dict):
                    continue
                estado.update(actualizacion)
                if "agente_destino" in actualizacion:
                    req.agente_destino = actualizacion["agente_destino"]
                    db.commit()
                db = _add_event(
                    db,
                    req.id,
                    "nodo_grafo",
                    {"nodo": nodo, "claves": list(actualizacion.keys())},
                )

        db, req = _refresh_db(db, request_id)
        req.respuesta_final = estado.get("respuesta_final")
        req.status = "completed"
        db.commit()
        db = _add_event(db, req.id, "completed", {})
    except Exception as exc:  # noqa: BLE001
        _mark_failed(request_id, str(exc))
    finally:
        if rag_token is not None:
            reset_rag_user_id(rag_token)
        if mem_token is not None:
            mem.reset_memory_user_id(mem_token)
        try:
            db.close()
        except Exception:
            pass


def aprobar_request(request_id: int, user_id: int, decision: str) -> Request:
    db = SessionLocal()
    rag_token = None
    mem_token = None
    try:
        req = (
            db.query(Request)
            .filter(Request.id == request_id, Request.user_id == user_id)
            .first()
        )
        if req is None:
            raise LookupError("Solicitud no encontrada")
        if req.status != "waiting_approval":
            raise ValueError("La solicitud no está pendiente de aprobación")

        rag_token = set_rag_user_id(req.user_id)
        mem_token = mem.set_memory_user_id(req.user_id)

        app = _app()
        config = {"configurable": {"thread_id": req.thread_id}}
        estado: dict = {}
        for chunk in app.stream(Command(resume=decision), config=config, stream_mode="updates"):
            for nodo, actualizacion in chunk.items():
                if nodo.startswith("__") or not isinstance(actualizacion, dict):
                    continue
                estado.update(actualizacion)
                _add_event(db, req.id, "nodo_grafo", {"nodo": nodo})

        aprobado = decision.strip().lower() in {"si", "sí", "s", "yes", "y"}
        if req.approval:
            req.approval.decision = "aprobado" if aprobado else "rechazado"
            req.approval.decided_at = datetime.now(timezone.utc)

        req.respuesta_final = estado.get("respuesta_final")
        req.status = "completed"
        db.commit()
        db.refresh(req)
        return req
    finally:
        if rag_token is not None:
            reset_rag_user_id(rag_token)
        if mem_token is not None:
            mem.reset_memory_user_id(mem_token)
        db.close()


def crear_request(db: Session, user_id: int, rol: str, peticion: str) -> Request:
    req = Request(
        user_id=user_id,
        thread_id=str(uuid.uuid4()),
        rol=rol,
        peticion=peticion,
        status="running",
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    return req
