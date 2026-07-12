"""Memoria de largo plazo en MySQL (misma interfaz conceptual que store JSON)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from src.db.models import MemoryFeedback, MemoryHistorico, MemoryPerfilAlumno
from src.db.session import SessionLocal

# ContextVar-like: user_id activo para el grafo
from contextvars import ContextVar

_memory_user_id: ContextVar[int | None] = ContextVar("memory_user_id", default=None)


def set_memory_user_id(user_id: int):
    return _memory_user_id.set(user_id)


def reset_memory_user_id(token) -> None:
    _memory_user_id.reset(token)


def _uid() -> int:
    uid = _memory_user_id.get()
    if uid is None:
        raise RuntimeError("memory user_id no configurado")
    return uid


def guardar(espacio: str, registro: dict, db: Session | None = None) -> None:
    own = db is None
    db = db or SessionLocal()
    try:
        user_id = _uid()
        if espacio == "feedback_docente":
            db.add(MemoryFeedback(user_id=user_id, payload=registro))
        elif espacio == "historico_generaciones":
            db.add(
                MemoryHistorico(
                    user_id=user_id,
                    tipo=registro.get("tipo", "examen"),
                    contenido=registro.get("contenido", ""),
                )
            )
        elif espacio == "perfil_alumno":
            db.add(
                MemoryPerfilAlumno(
                    user_id=user_id,
                    alumno_id=str(registro.get("alumno_id", "anonimo")),
                    nota=str(registro.get("nota", "")),
                )
            )
        else:
            raise ValueError(f"Espacio de memoria desconocido: {espacio}")
        db.commit()
    finally:
        if own:
            db.close()


def perfil_de_alumno(alumno_id: str, db: Session | None = None) -> str:
    own = db is None
    db = db or SessionLocal()
    try:
        user_id = _uid()
        entradas = (
            db.query(MemoryPerfilAlumno)
            .filter(
                MemoryPerfilAlumno.user_id == user_id,
                MemoryPerfilAlumno.alumno_id == alumno_id,
            )
            .order_by(MemoryPerfilAlumno.id.desc())
            .limit(5)
            .all()
        )
        if not entradas:
            return "Sin historial previo para este alumno."
        lineas = [
            f"- {e.created_at.date().isoformat() if e.created_at else '?'}: {e.nota}"
            for e in reversed(entradas)
        ]
        return "Historial reciente del alumno:\n" + "\n".join(lineas)
    finally:
        if own:
            db.close()
