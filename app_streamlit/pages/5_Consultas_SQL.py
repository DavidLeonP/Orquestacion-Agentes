"""SQL Agent: preguntas en lenguaje natural a la BD académica (solo docentes)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.api_client import ApiError
from lib.labels import sql_query_status_badge
from lib.session import client, render_sidebar, require_docente
from lib.ui import show_api_error

st.set_page_config(page_title="Consultas SQL", page_icon="🗄️", layout="wide")
require_docente()
render_sidebar()

st.title("Consultas SQL")
st.caption(
    "Agente SQL: pregunta en lenguaje natural sobre la base académica "
    "(matrícula, notas, asistencia). Genera y valida SELECT; nunca modifica datos."
)

EJEMPLOS = [
    "¿Cuántos alumnos hay en 3º ESO?",
    "¿Qué alumnos de 3º ESO tienen nota media superior a 8 en Tecnología?",
    "Lista la asistencia de Ana Pérez en octubre",
    "¿Cuál es la nota media por asignatura?",
]

api = client()
try:
    health = st.session_state.get("health") or {}
    sql_cfg = (health.get("sql_agent") or {}) if isinstance(health, dict) else {}
    if sql_cfg.get("configured") is False:
        st.warning(
            "El servidor no tiene `AGENT_DB_URI` configurado. "
            "Las consultas fallarán hasta que Ops lo defina en el `.env` de la API."
        )
    elif sql_cfg.get("configured"):
        st.caption(f"BD de negocio: `{sql_cfg.get('dialect', 'configurada')}`")

    st.markdown("**Ideas rápidas**")
    cols = st.columns(len(EJEMPLOS))
    for i, text in enumerate(EJEMPLOS):
        short = text[:36] + ("…" if len(text) > 36 else "")
        if cols[i].button(short, key=f"sql_sug_{i}", use_container_width=True, help=text):
            st.session_state["sql_pregunta_area"] = text
            st.rerun()

    if "sql_pregunta_area" not in st.session_state:
        st.session_state["sql_pregunta_area"] = ""

    with st.form("sql_query_form", clear_on_submit=False):
        pregunta = st.text_area(
            "Tu pregunta",
            height=100,
            placeholder=EJEMPLOS[0],
            key="sql_pregunta_area",
        )
        submitted = st.form_submit_button(
            "Preguntar al agente SQL", type="primary", use_container_width=True
        )

    if submitted:
        if not pregunta.strip():
            st.warning("Escribe una pregunta.")
        else:
            try:
                creado = api.create_sql_query(pregunta.strip())
                st.session_state["last_sql_query_id"] = creado["id"]
                st.session_state["sql_auto_poll"] = True
            except ApiError as exc:
                show_api_error(exc)

    query_id = st.session_state.get("last_sql_query_id")
    if query_id:
        st.divider()
        st.subheader(f"Consulta #{query_id}")

        should_poll = st.session_state.pop("sql_auto_poll", False)
        detalle: dict = {}
        if should_poll:
            status_box = st.status("Consultando la base de datos…", expanded=True)
            with status_box:
                placeholder = st.empty()
                started = time.time()
                deadline = started + 180.0
                while time.time() < deadline:
                    try:
                        detalle = api.get_sql_query(query_id)
                    except ApiError as exc:
                        status_box.update(label="Error al consultar", state="error")
                        show_api_error(exc)
                        break
                    status = detalle.get("status")
                    elapsed = int(time.time() - started)
                    placeholder.caption(
                        f"Estado: {sql_query_status_badge(status)} · {elapsed}s"
                    )
                    if status in {"completed", "failed"}:
                        status_box.update(
                            label=f"{sql_query_status_badge(status)} ({elapsed}s)",
                            state="complete" if status == "completed" else "error",
                        )
                        break
                    time.sleep(2.0)
                else:
                    status_box.update(label="Tiempo de espera agotado", state="error")
        else:
            try:
                detalle = api.get_sql_query(query_id)
            except ApiError as exc:
                show_api_error(exc)
                detalle = {}

        if detalle.get("status") == "completed":
            st.success("Respuesta del agente SQL")
            st.markdown(detalle.get("respuesta_final") or "_(sin respuesta)_")
            if detalle.get("sql_query"):
                with st.expander("Ver la consulta SQL ejecutada", expanded=False):
                    st.code(detalle["sql_query"], language="sql")
        elif detalle.get("status") == "failed":
            st.error(detalle.get("error") or "La consulta falló.")
        elif detalle.get("status") == "running":
            st.info("La consulta sigue en proceso. Pulsa **Actualizar**.")
            if st.button("Actualizar", key="sql_refresh"):
                st.session_state["sql_auto_poll"] = True
                st.rerun()

        if detalle:
            with st.expander("Ver pasos del agente"):
                try:
                    eventos = api.sql_query_events(query_id)
                except ApiError as exc:
                    eventos = []
                    show_api_error(exc)
                if not eventos:
                    st.caption("Sin eventos registrados.")
                for ev in eventos:
                    tipo = ev.get("tipo")
                    if tipo == "nodo_grafo":
                        payload = ev.get("payload") or {}
                        nodo = payload.get("nodo", "?")
                        sql_intentado = payload.get("sql_intentado")
                        linea = f"• `{nodo}`"
                        if sql_intentado:
                            linea += f" — `{sql_intentado}`"
                        st.write(linea)
                    elif tipo == "completed":
                        st.write("• Completada")
                    elif tipo == "failed":
                        st.write(
                            f"• Falló: {(ev.get('payload') or {}).get('error', '')}"
                        )
                    else:
                        st.write(f"• {tipo}")

    st.divider()
    st.subheader("Historial de consultas")
    try:
        queries = api.list_sql_queries()
    except ApiError as exc:
        show_api_error(exc)
        queries = []

    if not queries:
        st.info("Todavía no has hecho ninguna consulta.")
    else:
        for q in queries:
            qid = q["id"]
            label = (
                f"#{qid} · {sql_query_status_badge(q.get('status'))} · "
                f"{(q.get('pregunta') or '')[:80]}"
            )
            cols_h = st.columns([4, 1])
            cols_h[0].markdown(label)
            if cols_h[1].button("Ver", key=f"sql_open_{qid}", use_container_width=True):
                st.session_state["last_sql_query_id"] = qid
                st.session_state["sql_auto_poll"] = q.get("status") == "running"
                st.rerun()
finally:
    api.close()
