"""Usuario activo para RAG y memoria (ContextVars) en los clientes sin JWT.

El CLI (main.py), la API legado (legacy_chat_api.py) y la evaluación ejecutan el
grafo sin una solicitud autenticada: aquí se resuelve su usuario y se fija como
contexto de las tools RAG y de la memoria MySQL.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from contextlib import contextmanager

from src.db.models import User
from src.db.session import SessionLocal
from src.memory import mysql_store as mem
from src.rag.context import reset_rag_user_id, set_rag_user_id


def resolver_usuario_legado(crear: bool = False) -> int:
    """LEGACY_API_USER_ID, o el usuario LEGACY_API_USER_EMAIL.

    Si no existe: con `crear` (API legado) se crea como docente; si no (CLI), se
    aborta para no pisar el alta normal (registro o seed) con otra contraseña.
    """
    if os.getenv("LEGACY_API_USER_ID"):
        return int(os.environ["LEGACY_API_USER_ID"])
    email = os.getenv("LEGACY_API_USER_EMAIL", "demo@instituto.local").lower()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if user is None:
            if not crear:
                raise SystemExit(
                    f"Usuario {email} no existe: regístralo (POST /auth/register) "
                    "o define LEGACY_API_USER_EMAIL / LEGACY_API_USER_ID"
                )
            from src.api.security import hash_password

            user = User(email=email, password_hash=hash_password("legacy-api-demo"), rol="docente")
            db.add(user)
            db.commit()
            db.refresh(user)
        return user.id
    finally:
        db.close()


@contextmanager
def contexto_usuario(user_id: int) -> Generator[int, None, None]:
    rag_token = set_rag_user_id(user_id)
    mem_token = mem.set_memory_user_id(user_id)
    try:
        yield user_id
    finally:
        reset_rag_user_id(rag_token)
        mem.reset_memory_user_id(mem_token)
