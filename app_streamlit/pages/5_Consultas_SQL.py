"""SQL Agent: preguntas NL a la BD académica (solo docentes).

Incluye reflexión/validación, HITL de aclaración (`waiting_clarification`) y
trazas nodo a nodo del grafo LangGraph (mismo flujo que LangSmith).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

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
    "Agente SQL con reflexión: valida la respuesta, pide aclaración si hay duda "
    "y aprende en Chroma. Solo SELECT sobre la BD académica sintética."
)

EJEMPLOS = [
    "¿Cuáles son los 5 estudiantes de Psicología con mejor promedio en el año lectivo vigente?",
    "Lista los estudiantes del año anterior que suspendieron alguna materia (nota < 5), en orden alfabético.",
    "Dame el récord estudiantil completo de Ana Benítez Ortiz.",
    "¿Cuáles son los estudiantes que se matricularon el año pasado? Total y primeros 20.",
]

ACLARACIONES_SUGERIDAS = [
    (
        "Año pasado / vigente",
        "«Año pasado» = periodo con MAX(anio_fin)-1; «vigente» = MAX(anio_fin). "
        "Matrículas vía matriculas→ofertas→periodos, no anio_ingreso.",
    ),
    (
        "Suspendido",
        "Suspender = calificaciones.nota < 5.0 (escala 0–10).",
    ),
    (
        "Quinto curso",
        "Quinto curso = anio_ingreso = anio_inicio del periodo vigente − 4.",
    ),
]


def _eventos_por_tipo(eventos: list[dict[str, Any]], tipo: str) -> list[dict[str, Any]]:
    return [e for e in eventos if e.get("tipo") == tipo]


def _ultimo_payload(eventos: list[dict[str, Any]], tipo: str) -> dict[str, Any]:
    matched = _eventos_por_tipo(eventos, tipo)
    if not matched:
        return {}
    payload = matched[-1].get("payload") or {}
    return payload if isinstance(payload, dict) else {}


def _render_pasos(eventos: list[dict[str, Any]]) -> None:
    if not eventos:
        st.caption("Sin eventos registrados.")
        return
    for ev in eventos:
        tipo = ev.get("tipo")
        payload = ev.get("payload") or {}
        if tipo == "nodo_grafo":
            nodo = payload.get("nodo", "?")
            linea = f"• `{nodo}`"
            if payload.get("sql_intentado"):
                linea += f" — `{payload['sql_intentado']}`"
            st.write(linea)
            veredicto = payload.get("veredicto")
            if isinstance(veredicto, dict):
                ok = veredicto.get("aprobado")
                st.caption(
                    f"  veredicto: {'✅ aprobado' if ok else '❌ rechazado'}"
                    + (
                        f" · aclaración={'sí' if veredicto.get('necesita_aclaracion') else 'no'}"
                    )
                )
                for m in (veredicto.get("motivos") or [])[:3]:
                    st.caption(f"  – {m}")
            lecciones = payload.get("lecciones")
            if isinstance(lecciones, list) and lecciones:
                st.caption(f"  lecciones: {len(lecciones)}")
                st.caption(f"  última: {str(lecciones[-1])[:180]}")
        elif tipo == "waiting_clarification":
            st.write("• ❓ Pendiente de aclaración humana")
            if payload.get("pregunta_aclaracion"):
                st.caption(f"  {payload['pregunta_aclaracion']}")
        elif tipo == "aclaracion_recibida":
            ac = payload.get("aclaracion", "")
            st.write(f"• Aclaración recibida: {str(ac)[:160]}")
        elif tipo == "completed":
            st.write("• ✅ Completada")
        elif tipo == "failed":
            st.write(f"• ❌ Falló: {payload.get('error', '')}")
        else:
            st.write(f"• {tipo}")


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

    with st.expander("Cómo funciona (reflexión + LangGraph)", expanded=False):
        st.markdown(
            """
1. Lista tablas y esquema (+ grafo de conocimiento).
2. Recupera **aclaraciones aprendidas** en Chroma.
3. Genera SQL → corrige → ejecuta (solo SELECT).
4. **Valida** la respuesta; si falla, **reflexiona** y reintenta.
5. Si hay **duda**, queda en `waiting_clarification` hasta tu aclaración.
6. La aclaración se archiva en Chroma para próximas consultas.
            """
        )

    st.markdown("**Ideas rápidas**")
    cols = st.columns(2)
    for i, text in enumerate(EJEMPLOS):
        short = text[:52] + ("…" if len(text) > 52 else "")
        if cols[i % 2].button(short, key=f"sql_sug_{i}", use_container_width=True, help=text):
            st.session_state["sql_pregunta_area"] = text
            st.rerun()

    if "sql_pregunta_area" not in st.session_state:
        st.session_state["sql_pregunta_area"] = ""

    with st.form("sql_query_form", clear_on_submit=False):
        pregunta = st.text_area(
            "Tu pregunta",
            height=110,
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
                deadline = started + 300.0
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
                    if status in {"completed", "failed", "waiting_clarification"}:
                        status_box.update(
                            label=f"{sql_query_status_badge(status)} ({elapsed}s)",
                            state="complete"
                            if status in {"completed", "waiting_clarification"}
                            else "error",
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

        eventos: list[dict[str, Any]] = []
        if detalle:
            try:
                eventos = api.sql_query_events(query_id)
            except ApiError as exc:
                show_api_error(exc)

        status = detalle.get("status")
        if status == "completed":
            st.success("Respuesta del agente SQL")
            st.markdown(detalle.get("respuesta_final") or "_(sin respuesta)_")
            if detalle.get("sql_query"):
                with st.expander("Ver la consulta SQL ejecutada", expanded=True):
                    st.code(detalle["sql_query"], language="sql")
        elif status == "waiting_clarification":
            hitl = _ultimo_payload(eventos, "waiting_clarification")
            st.warning("El agente necesita una aclaración (reflexión / duda semántica).")
            st.markdown("**Pregunta del agente**")
            st.markdown(
                hitl.get("pregunta_aclaracion")
                or detalle.get("respuesta_final")
                or "_(sin pregunta)_"
            )
            motivos = hitl.get("motivos") or []
            if motivos:
                st.markdown("**Motivos de la validación**")
                for m in motivos:
                    st.write(f"- {m}")
            if hitl.get("borrador_respuesta"):
                with st.expander("Borrador rechazado / provisional", expanded=False):
                    st.markdown(str(hitl["borrador_respuesta"])[:4000])
            if hitl.get("sql_propuesto"):
                with st.expander("SQL propuesto", expanded=False):
                    st.code(str(hitl["sql_propuesto"]), language="sql")

            st.markdown("**Aclaraciones rápidas**")
            sug_cols = st.columns(len(ACLARACIONES_SUGERIDAS))
            for i, (titulo, texto) in enumerate(ACLARACIONES_SUGERIDAS):
                if sug_cols[i].button(titulo, key=f"sql_acl_sug_{query_id}_{i}", help=texto):
                    st.session_state[f"sql_aclaracion_{query_id}"] = texto
                    st.rerun()

            with st.form(f"sql_clarify_{query_id}"):
                aclaracion = st.text_area(
                    "Tu aclaración",
                    height=110,
                    key=f"sql_aclaracion_{query_id}",
                    placeholder=ACLARACIONES_SUGERIDAS[0][1],
                )
                enviar = st.form_submit_button(
                    "Enviar aclaración y continuar",
                    type="primary",
                    use_container_width=True,
                )
            if enviar:
                if not aclaracion.strip():
                    st.warning("Escribe la aclaración.")
                else:
                    try:
                        api.clarify_sql_query(query_id, aclaracion.strip())
                        st.session_state["sql_auto_poll"] = True
                        st.rerun()
                    except ApiError as exc:
                        show_api_error(exc)
        elif status == "failed":
            st.error(detalle.get("error") or "La consulta falló.")
        elif status == "running":
            st.info("La consulta sigue en proceso. Pulsa **Actualizar**.")
            if st.button("Actualizar", key="sql_refresh"):
                st.session_state["sql_auto_poll"] = True
                st.rerun()

        if detalle:
            with st.expander("Ver pasos del agente (LangGraph)", expanded=True):
                _render_pasos(eventos)

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
