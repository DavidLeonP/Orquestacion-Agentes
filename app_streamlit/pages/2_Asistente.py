"""Nueva petición al orquestador (polling de estado)."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.api_client import ApiError
from lib.session import client, is_docente, render_sidebar, require_auth
from lib.ui import poll_request, render_request_result, show_api_error

st.set_page_config(page_title="Asistente", page_icon="🤖", layout="wide")
user = require_auth()
render_sidebar()

st.title("Asistente")
st.caption(
    "Crea una solicitud async en la API. Streamlit solo hace polling del estado."
)

if is_docente():
    placeholders = [
        "Genera un examen de 6 preguntas sobre electricidad para 3º ESO",
        "Estructura la unidad de circuitos en sesiones",
        "Propón una rúbrica de evaluación para el proyecto de tecnología",
    ]
    st.markdown("**Sugerencias (docente)**")
else:
    placeholders = [
        "¿Qué es la ley de Ohm?",
        "Explícame la diferencia entre serie y paralelo",
        "Ayúdame a estudiar circuitos eléctricos",
    ]
    st.markdown("**Sugerencias (alumno · tutor)**")

cols = st.columns(len(placeholders))
for i, text in enumerate(placeholders):
    if cols[i].button(text[:48] + ("…" if len(text) > 48 else ""), key=f"sug_{i}"):
        st.session_state["peticion_draft"] = text

peticion = st.text_area(
    "Petición",
    value=st.session_state.get("peticion_draft", ""),
    height=140,
    placeholder=placeholders[0],
)

api = client()
try:
    if st.button("Enviar", type="primary", use_container_width=True):
        if not peticion.strip():
            st.warning("Escribe una petición.")
        else:
            try:
                req = api.create_request(peticion.strip())
                st.session_state["last_request_id"] = req["id"]
                st.info(
                    f"Request `{req['id']}` creada · thread `{req['thread_id']}` "
                    f"· status `{req['status']}`"
                )
                result = poll_request(api, req["id"])
                st.session_state["last_request"] = result
            except ApiError as exc:
                show_api_error(exc)

    last = st.session_state.get("last_request")
    if last:
        st.divider()
        st.subheader("Resultado")
        render_request_result(last)

        if last.get("status") == "waiting_approval" and is_docente():
            st.page_link("pages/4_Aprobaciones.py", label="Ir a Aprobaciones →")
finally:
    api.close()
