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
    "Pregunta en lenguaje natural sobre la base de datos académica del instituto "
    "(matrícula, notas, asistencia). El agente genera y valida la consulta SQL por ti; "
    "nunca modifica datos, solo lectura."
)

api = client()
try:
    with st.form("sql_query_form", clear_on_submit=True):
        pregunta = st.text_area(
            "Tu pregunta",
            placeholder="Ej: ¿Cuántos alumnos de 3º ESO tienen una nota media superior a 8?",
            height=100,
        )
        submitted = st.form_submit_button("Preguntar", type="primary", use_container_width=True)

    if submitted:
        if not pregunta.strip():
            st.warning("Escribe una pregunta.")
        else:
            try:
                creado = api.create_sql_query(pregunta.strip())
                st.session_state["last_sql_query_id"] = creado["id"]
            except ApiError as exc:
                show_api_error(exc)

    query_id = st.session_state.get("last_sql_query_id")
    if query_id:
        st.divider()
        st.subheader(f"Consulta #{query_id}")

        status_box = st.status("Consultando la base de datos…", expanded=True)
        detalle: dict = {}
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
                placeholder.caption(f"Estado: {sql_query_status_badge(status)} · {elapsed}s")
                if status in {"completed", "failed"}:
                    status_box.update(
                        label=f"{sql_query_status_badge(status)} ({elapsed}s)",
                        state="complete" if status == "completed" else "error",
                    )
                    break
                time.sleep(2.0)
            else:
                status_box.update(label="Tiempo de espera agotado", state="error")

        if detalle.get("status") == "completed":
            st.success("Respuesta")
            st.markdown(detalle.get("respuesta_final") or "_(sin respuesta)_")
            if detalle.get("sql_query"):
                with st.expander("Ver la consulta SQL ejecutada"):
                    st.code(detalle["sql_query"], language="sql")
        elif detalle.get("status") == "failed":
            st.error(detalle.get("error") or "La consulta falló.")

        if detalle:
            with st.expander("Ver pasos del proceso"):
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
                        linea = f"• {nodo}"
                        if sql_intentado:
                            linea += f" — `{sql_intentado}`"
                        st.write(linea)
                    elif tipo == "completed":
                        st.write("• Completada")
                    elif tipo == "failed":
                        st.write(f"• Falló: {(ev.get('payload') or {}).get('error', '')}")
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
        rows = [
            {
                "Nº": q["id"],
                "Estado": sql_query_status_badge(q.get("status")),
                "Pregunta": (q.get("pregunta") or "")[:100],
                "Actualizada": q.get("updated_at"),
            }
            for q in queries
        ]
        st.dataframe(rows, use_container_width=True, hide_index=True)
finally:
    api.close()
