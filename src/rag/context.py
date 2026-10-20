"""Contexto de usuario y evidencia para tools RAG (ContextVar)."""

from contextvars import ContextVar

_user_id: ContextVar[int | None] = ContextVar("rag_user_id", default=None)
# Fuentes que devolvieron las tools durante el agente en curso (como EVIDENCIA en
# el notebook): el verificador comprueba que el examen solo cite lo consultado.
_evidencia: ContextVar[list[str] | None] = ContextVar("rag_evidencia", default=None)


def set_rag_user_id(user_id: int):
    return _user_id.set(user_id)


def reset_rag_user_id(token) -> None:
    _user_id.reset(token)


def get_rag_user_id() -> int:
    uid = _user_id.get()
    if uid is None:
        raise RuntimeError("user_id RAG no configurado en el contexto")
    return uid


def rag_user_id_actual() -> int | None:
    """user_id del contexto, o None si nadie lo fijó (p. ej. tests sin usuario)."""
    return _user_id.get()


def iniciar_evidencia() -> list[str]:
    """Empieza a registrar fuentes; la lista se llena mientras dure el contexto."""
    vistas: list[str] = []
    _evidencia.set(vistas)
    return vistas


def anotar_fuentes(fuentes: list[str]) -> None:
    vistas = _evidencia.get()
    if vistas is not None:
        vistas.extend(f for f in fuentes if f and f not in vistas)
