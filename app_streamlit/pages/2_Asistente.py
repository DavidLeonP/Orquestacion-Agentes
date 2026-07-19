"""Nueva petición al orquestador (polling de estado)."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.api_client import ApiError
from lib.labels import format_llm_badge
from lib.session import client, is_docente, render_sidebar, require_auth
from lib.ui import poll_request, render_request_result, show_api_error

st.set_page_config(page_title="Asistente", page_icon="💬", layout="wide")
require_auth()
render_sidebar()

st.title("Asistente")
st.caption(
    "Escribe lo que necesitas. El orquestador elige el agente adecuado y te muestra el progreso."
)

health = st.session_state.get("health")
model_title, model_detail = format_llm_badge(health)
st.caption(f"Modelo: **{model_title}** · {model_detail}")

if is_docente():
    placeholders = [
        "Genera un examen de 6 preguntas sobre electricidad para 3º ESO",
        "Estructura la unidad de circuitos en sesiones",
        "Propón una rúbrica de evaluación para el proyecto de tecnología",
    ]
    st.markdown("**Ideas rápidas (docente)**")
else:
    placeholders = [
        "¿Qué es la ley de Ohm?",
        "Explícame la diferencia entre serie y paralelo",
        "Ayúdame a estudiar circuitos eléctricos",
    ]
    st.markdown("**Ideas rápidas (alumno)**")

cols = st.columns(len(placeholders))
for i, text in enumerate(placeholders):
    short = text[:40] + ("…" if len(text) > 40 else "")
    if cols[i].button(short, key=f"sug_{i}", use_container_width=True, help=text):
        st.session_state["peticion_draft"] = text
        st.session_state["peticion_area"] = text
        st.session_state["clear_peticion"] = False
        st.rerun()

with st.expander("Ver ejemplos completos"):
    for text in placeholders:
        st.markdown(f"- {text}")

if st.session_state.pop("clear_peticion", False):
    st.session_state["peticion_draft"] = ""
    st.session_state["peticion_area"] = ""

if "peticion_area" not in st.session_state:
    st.session_state["peticion_area"] = st.session_state.get("peticion_draft", "")

api = client()
try:
    with st.form("peticion_form", clear_on_submit=False):
        peticion = st.text_area(
            "Tu petición",
            height=140,
            placeholder=placeholders[0],
            key="peticion_area",
        )
        submitted = st.form_submit_button(
            "Enviar petición", type="primary", use_container_width=True
        )

    if submitted:
        text = (peticion or "").strip()
        if not text:
            st.warning("Escribe una petición.")
        else:
            st.session_state["peticion_draft"] = text
            try:
                with st.spinner("Enviando al orquestador…"):
                    req = api.create_request(text)
                st.session_state["last_request_id"] = req["id"]
                st.success(
                    f"Petición **#{req['id']}** recibida. "
                    "Ahora los agentes trabajan; el progreso aparece a continuación."
                )
                result = poll_request(api, req["id"])
                st.session_state["last_request"] = result
                from lib.session import refresh_pending_approvals

                if is_docente():
                    refresh_pending_approvals(api)
            except ApiError as exc:
                show_api_error(exc)

    last = st.session_state.get("last_request")
    if last:
        st.divider()
        st.subheader("Resultado")
        updated = render_request_result(
            last, api=api, show_inline_approve=True, key_prefix="asistente"
        )
        if updated:
            st.session_state["last_request"] = updated
            from lib.session import refresh_pending_approvals

            if is_docente():
                refresh_pending_approvals(api)
            st.rerun()
finally:
    api.close()
