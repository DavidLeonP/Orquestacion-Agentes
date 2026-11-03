"""Ejecución del SQL Agent para la API REST.

Mismo patrón que `orchestrator_runner.py`: crea la `SqlQuery`, la ejecuta en
background con `app.stream(..., stream_mode="updates")`, persiste un evento
por nodo visitado y soporta HITL de aclaración (`waiting_clarification` →
`Command(resume=…)`).
"""

from __future__ import annotations

import uuid

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from sqlalchemy.orm import Session

from src.db.models import SqlQuery, SqlQueryEvent
from src.db.session import SessionLocal
from src.observability.trazas import TrazasSolicitud, registrar_evento
from src.sql_agent.database import get_sql_database
from src.sql_agent.graph import RECURSION_LIMIT, construir_grafo

_CHECKPOINTER = MemorySaver()
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


def _stream_hasta_fin_o_hitl(
    db: Session,
    q: SqlQuery,
    stream,
) -> bool:
    """Consume el stream. True si se quedó en waiting_clarification."""
    interrumpido = False
    try:
        for chunk in stream:
            if "__interrupt__" in chunk:
                interrupt_data = chunk["__interrupt__"][0].value
                if not isinstance(interrupt_data, dict):
                    interrupt_data = {"mensaje": str(interrupt_data)}
                q.status = "waiting_clarification"
                # La pregunta al docente viaja en respuesta_final mientras espera.
                q.respuesta_final = (
                    interrupt_data.get("pregunta_aclaracion")
                    or interrupt_data.get("mensaje")
                    or "Se necesita una aclaración."
                )
                db.add(
                    SqlQueryEvent(
                        sql_query_id=q.id,
                        tipo="waiting_clarification",
                        payload=interrupt_data,
                    )
                )
                db.commit()
                registrar_evento("waiting_clarification", **{
                    k: interrupt_data.get(k)
                    for k in ("pregunta_aclaracion", "motivos", "mensaje")
                    if k in interrupt_data
                })
                interrumpido = True
                break

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
                if "veredicto" in actualizacion:
                    payload["veredicto"] = actualizacion.get("veredicto")
                if "lecciones" in actualizacion:
                    payload["lecciones"] = actualizacion.get("lecciones")
                registrar_evento("nodo_grafo", **payload)
                db.add(SqlQueryEvent(sql_query_id=q.id, tipo="nodo_grafo", payload=payload))
                db.commit()
    except GeneratorExit:
        return interrumpido
    finally:
        close = getattr(stream, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # noqa: BLE001
                pass
    return interrumpido


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
        entrada = {
            "messages": [("user", q.pregunta)],
            "peticion": q.pregunta,
            "lecciones": [],
            "clarificaciones": [],
            "intentos_validacion": 0,
        }

        stream = app.stream(entrada, config=run_config, stream_mode="updates")
        if _stream_hasta_fin_o_hitl(db, q, stream):
            return

        estado_final = app.get_state(run_config).values
        mensajes = estado_final.get("messages", [])

        q = db.get(SqlQuery, query_id)
        q.respuesta_final = _extraer_respuesta_final(mensajes)
        q.sql_query = _extraer_sql_query(mensajes) or estado_final.get("sql_final")
        q.status = "completed"
        db.add(SqlQueryEvent(sql_query_id=q.id, tipo="completed", payload={}))
        db.commit()
    except GeneratorExit:
        return
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        _mark_failed(query_id, str(exc))
    finally:
        db.close()


def aclarar_query(
    query_id: int,
    user_id: int,
    aclaracion: str,
    agent_db_uri: str | None = None,
) -> None:
    """Reanuda el grafo tras `waiting_clarification` (BackgroundTask).

    El router ya validó el estado y registró `aclaracion_recibida`. Aquí solo
    se hace `Command(resume=…)`: el nodo `aclaracion_humana` archiva en Chroma.
    """
    tenant = str(user_id)
    db = SessionLocal()
    try:
        q = (
            db.query(SqlQuery)
            .filter(SqlQuery.id == query_id, SqlQuery.user_id == user_id)
            .first()
        )
        if q is None:
            return
        thread_id = q.thread_id
        pregunta = q.pregunta
        q.status = "running"
        q.error = None
        db.commit()
    finally:
        db.close()

    try:
        with TrazasSolicitud(str(query_id), rol="sql_agent", peticion=pregunta):
            _reanudar_con_aclaracion(query_id, tenant, thread_id, aclaracion, agent_db_uri)
    except Exception as exc:  # noqa: BLE001
        _mark_failed(query_id, str(exc))


def _reanudar_con_aclaracion(
    query_id: int,
    tenant: str,
    thread_id: str,
    aclaracion: str,
    agent_db_uri: str | None,
) -> None:
    db = SessionLocal()
    try:
        q = db.get(SqlQuery, query_id)
        if q is None:
            return
        app = _app(tenant, agent_db_uri)
        run_config = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": RECURSION_LIMIT,
        }
        stream = app.stream(
            Command(resume={"aclaracion": aclaracion}),
            config=run_config,
            stream_mode="updates",
        )
        if _stream_hasta_fin_o_hitl(db, q, stream):
            return

        estado_final = app.get_state(run_config).values
        mensajes = estado_final.get("messages", [])
        q = db.get(SqlQuery, query_id)
        q.respuesta_final = _extraer_respuesta_final(mensajes)
        q.sql_query = _extraer_sql_query(mensajes) or estado_final.get("sql_final")
        q.status = "completed"
        db.add(SqlQueryEvent(sql_query_id=q.id, tipo="completed", payload={}))
        db.commit()
    except GeneratorExit:
        return
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        _mark_failed(query_id, str(exc))
    finally:
        db.close()
