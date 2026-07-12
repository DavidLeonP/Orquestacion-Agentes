"""Contexto de usuario para tools RAG (ContextVar)."""

from contextvars import ContextVar

_user_id: ContextVar[int | None] = ContextVar("rag_user_id", default=None)


def set_rag_user_id(user_id: int):
    return _user_id.set(user_id)


def reset_rag_user_id(token) -> None:
    _user_id.reset(token)


def get_rag_user_id() -> int:
    uid = _user_id.get()
    if uid is None:
        raise RuntimeError("user_id RAG no configurado en el contexto")
    return uid
