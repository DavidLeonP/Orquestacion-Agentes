"""Conexión a la BD de negocio que el SQL Agent consulta (AGENT_DB_URI).

Distinta de la BD de metadatos de la app (src/db/session.py), que guarda
usuarios, RAG y solicitudes, no los datos de negocio consultables en
lenguaje natural.

`AGENT_DB_URI` en .env es solo el valor por defecto: cada request a
POST /sql-queries puede enviar su propia cadena de conexión (`agent_db_uri`)
para apuntar a una BD de negocio distinta sin reiniciar el proceso (ver
SqlQueryCreateIn en src/api/schemas.py). Las conexiones se cachean por
`(tenant, uri)` — no solo por URI — para que un `agent_db_uri` reutilizado o
reapuntado nunca sirva silenciosamente la conexión cacheada de otro tenant.
`tenant` es hoy el `user_id` del docente autenticado.
"""

from __future__ import annotations

from functools import lru_cache

from langchain_community.utilities import SQLDatabase
from sqlalchemy import text

from src import config

# Máximo de BDs de negocio distintas mantenidas abiertas a la vez (por tenant).
_MAX_CONEXIONES_CACHEADAS = 32


@lru_cache(maxsize=_MAX_CONEXIONES_CACHEADAS)
def _sql_database_por_tenant(tenant: str, uri: str) -> SQLDatabase:
    db = SQLDatabase.from_uri(uri)
    # Segunda capa de defensa, independiente del permiso GRANT SELECT del
    # usuario de BD (.env.example): la sesión de MySQL/MariaDB queda en modo
    # solo-lectura, así que cualquier DML que se cuele pasado el validador
    # AST (sql_validator.py) fallará también a nivel de sesión. SQLite (usado
    # en tests) no soporta esta sentencia; se omite ahí.
    if db._engine.dialect.name in {"mysql", "mariadb"}:
        with db._engine.connect() as con:
            con.execute(text("SET SESSION TRANSACTION READ ONLY"))
            con.commit()
    return db


def get_sql_database(tenant: str, uri: str | None = None) -> SQLDatabase:
    """Devuelve la SQLDatabase para `(tenant, uri)`, o `(tenant, AGENT_DB_URI del .env)`."""
    uri = uri or config.AGENT_DB_URI
    if not uri:
        raise RuntimeError(
            "AGENT_DB_URI no está configurado. Define la cadena de conexión a "
            "la base de datos de negocio en .env (ver .env.example), o envía "
            "agent_db_uri en el request."
        )
    if not tenant:
        raise RuntimeError("tenant (user_id) es obligatorio para resolver la BD de negocio.")
    return _sql_database_por_tenant(tenant, uri)
