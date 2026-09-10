"""Ejecución del SQL Agent para la API REST.

Mismo patrón que `orchestrator_runner.py`: crea la `SqlQuery`, la ejecuta en
background con `app.stream(..., stream_mode="updates")`, persiste un evento
por nodo visitado y nunca deja propagar excepciones fuera del BackgroundTask
(la respuesta HTTP 202 ya se envió).
"""

from __future__ import annotations

import uuid

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy.orm import Session

from src.db.models import SqlQuery, SqlQueryEvent
from src.db.session import SessionLocal
from src.observability.trazas import TrazasSolicitud, registrar_evento
from src.sql_agent.database import get_sql_database
from src.sql_agent.graph import RECURSION_LIMIT, construir_grafo

# Checkpointer de proceso: basta para una sola query por thread_id mientras
# el proceso viva.
_CHECKPOINTER = MemorySaver()
# Un grafo compilado por cada (tenant, AGENT_DB_URI) distinto visto (las
# tools del grafo cierran sobre la SQLDatabase, así que no se puede compartir
# un solo grafo entre tenants ni entre BDs de negocio distintas). La clave
# siempre incluye `tenant` — nunca solo el URI — para que un `agent_db_uri`
# reutilizado o reapuntado no sirva por accidente el grafo de otro tenant.
_APPS: dict[tuple[str, str], object] = {}


def _app(tenant: str, agent_db_uri: str | None = None):
    clave = (tenant, agent_db_uri or "")
    if clave not in _APPS:
        db = get_sql_database(tenant, agent_db_uri)
        _APPS[clave] = construir_grafo(
            tenant=tenant, agent_db_uri=agent_db_uri, db=db, checkpointer=_CHECKPOINTER
        )
    return _APPS[clave]


def _mark_failed(query_id: int, error: str) -> None:
    db = SessionLocal()
    try:
        q = db.get(SqlQuery, query_id)
        if q is None:
            return
        q.status = "failed"
        q.error = error[:4000]
        db.add(SqlQueryEvent(sql_query_id=query_id, tipo="failed", payload={"error": error[:500]}))
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def _extraer_respuesta_final(messages: list) -> str | None:
    for m in reversed(messages):
        if isinstance(m, AIMessage) and m.tool_calls:
            for tc in m.tool_calls:
                if tc["name"] == "SubmitFinalAnswer":
                    return tc["args"].get("final_answer")
    return None


def _extraer_sql_query(messages: list) -> str | None:
    """Última consulta db_query_tool ejecutada con éxito (para auditoría)."""
    ultimo_ok: str | None = None
    for i, m in enumerate(messages):
        if not (isinstance(m, AIMessage) and m.tool_calls):
            continue
        for tc in m.tool_calls:
            if tc["name"] != "db_query_tool":
                continue
            resultado = next(
                (
                    n
                    for n in messages[i + 1 :]
                    if isinstance(n, ToolMessage) and n.tool_call_id == tc["id"]
                ),
                None,
            )
            contenido = str(resultado.content) if resultado is not None else ""
            if resultado is not None and not contenido.startswith("Error:"):
                ultimo_ok = tc["args"].get("query")
    return ultimo_ok


def _sql_intentado(actualizacion: dict) -> str | None:
    """Extrae el SQL que un nodo intentó ejecutar/corregir, para el evento de auditoría."""
    for m in actualizacion.get("messages", []):
        tool_calls = getattr(m, "tool_calls", None) or []
        for tc in tool_calls:
            if tc.get("name") == "db_query_tool":
                return tc.get("args", {}).get("query")
    return None


def crear_query(db: Session, user_id: int, pregunta: str) -> SqlQuery:
    q = SqlQuery(
        user_id=user_id,
        thread_id=str(uuid.uuid4()),
        pregunta=pregunta,
        status="running",
    )
    db.add(q)
    db.commit()
    db.refresh(q)
    return q


def ejecutar_query(query_id: int, user_id: int, agent_db_uri: str | None = None) -> None:
    """Ejecuta el grafo hasta completar.

    `agent_db_uri` viaja solo como argumento de esta llamada en background:
    no se persiste en la SqlQuery ni se incluye en ningún evento o mensaje
    de error. `tenant` (= `user_id`) sí queda persistido en la SqlQuery desde
    `crear_query`, porque identifica al docente dueño de la consulta.

    Nunca propaga excepciones: BackgroundTasks de FastAPI las re-lanzaría y
    la respuesta HTTP 202 ya se envió al cliente.
    """
    tenant = str(user_id)
    db = SessionLocal()
    try:
        q = db.get(SqlQuery, query_id)
        pregunta = q.pregunta if q else ""
    finally:
        db.close()
    try:
        with TrazasSolicitud(str(query_id), rol="sql_agent", peticion=pregunta):
            _ejecutar_query_impl(query_id, tenant, agent_db_uri)
    except Exception as exc:  # noqa: BLE001
        _mark_failed(query_id, str(exc))


def _ejecutar_query_impl(query_id: int, tenant: str, agent_db_uri: str | None = None) -> None:
    db = SessionLocal()
    try:
        q = db.get(SqlQuery, query_id)
        if q is None:
            return

        app = _app(tenant, agent_db_uri)
        run_config = {
            "configurable": {"thread_id": q.thread_id},
            "recursion_limit": RECURSION_LIMIT,
        }
        entrada = {"messages": [("user", q.pregunta)]}

        for chunk in app.stream(entrada, config=run_config, stream_mode="updates"):
            for nodo, actualizacion in chunk.items():
                if nodo.startswith("__") or not isinstance(actualizacion, dict):
                    continue
                payload = {
                    "nodo": nodo,
                    "mensajes_nuevos": len(actualizacion.get("messages", [])),
                }
                sql = _sql_intentado(actualizacion)
                if sql:
                    payload["sql_intentado"] = sql
                registrar_evento("nodo_grafo", **payload)
                db.add(SqlQueryEvent(sql_query_id=q.id, tipo="nodo_grafo", payload=payload))
                db.commit()

        estado_final = app.get_state(run_config).values
        mensajes = estado_final.get("messages", [])

        q = db.get(SqlQuery, query_id)
        q.respuesta_final = _extraer_respuesta_final(mensajes)
        q.sql_query = _extraer_sql_query(mensajes)
        q.status = "completed"
        db.add(SqlQueryEvent(sql_query_id=q.id, tipo="completed", payload={}))
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        _mark_failed(query_id, str(exc))
    finally:
        db.close()
