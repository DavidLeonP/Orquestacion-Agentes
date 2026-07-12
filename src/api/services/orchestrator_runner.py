"""Ejecución del orquestador para la API REST."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from sqlalchemy.orm import Session

from src.db.models import Approval, Request, RequestEvent
from src.db.session import SessionLocal
from src.memory import mysql_store as mem
from src.orchestrator.graph import construir_grafo
from src.rag.context import reset_rag_user_id, set_rag_user_id

# Checkpointer de proceso (HITL entre requests HTTP mientras el proceso viva).
# Para multi-worker en producción conviene un checkpointer externo.
_CHECKPOINTER = MemorySaver()
_APP = None


def _app():
    global _APP
    if _APP is None:
        _APP = construir_grafo(checkpointer=_CHECKPOINTER, memory_backend=mem)
    return _APP


def _add_event(db: Session, request_id: int, tipo: str, payload: dict | None = None) -> None:
    db.add(RequestEvent(request_id=request_id, tipo=tipo, payload=payload or {}))
    db.commit()


def ejecutar_request(request_id: int) -> None:
    """Ejecuta el grafo hasta completar o interrupt HITL."""
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
            if "__interrupt__" in chunk:
                interrupt_data = chunk["__interrupt__"][0].value
                req.status = "waiting_approval"
                req.agente_destino = estado.get("agente_destino") or req.agente_destino
                if req.approval is None:
                    db.add(
                        Approval(
                            request_id=req.id,
                            borrador=interrupt_data.get("borrador", ""),
                            veredicto=interrupt_data.get("veredicto", ""),
                            decision="pending",
                        )
                    )
                else:
                    req.approval.borrador = interrupt_data.get("borrador", "")
                    req.approval.veredicto = interrupt_data.get("veredicto", "")
                    req.approval.decision = "pending"
                db.commit()
                _add_event(db, req.id, "waiting_approval", {"mensaje": interrupt_data.get("mensaje")})
                return

            for nodo, actualizacion in chunk.items():
                if nodo.startswith("__") or not isinstance(actualizacion, dict):
                    continue
                estado.update(actualizacion)
                if "agente_destino" in actualizacion:
                    req.agente_destino = actualizacion["agente_destino"]
                    db.commit()
                _add_event(db, req.id, "nodo_grafo", {"nodo": nodo, "claves": list(actualizacion.keys())})

        req.respuesta_final = estado.get("respuesta_final")
        req.status = "completed"
        db.commit()
        _add_event(db, req.id, "completed", {})
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        req = db.get(Request, request_id)
        if req:
            req.status = "failed"
            req.error = str(exc)[:4000]
            db.commit()
            _add_event(db, req.id, "failed", {"error": str(exc)[:500]})
    finally:
        if rag_token is not None:
            reset_rag_user_id(rag_token)
        if mem_token is not None:
            mem.reset_memory_user_id(mem_token)
        db.close()


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
