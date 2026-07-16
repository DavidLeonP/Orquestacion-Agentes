"""Asistente IA Educación — UI Streamlit (cliente de la API JWT)."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.api_client import ApiClient, ApiError
from lib.session import init_session, is_authenticated, login, render_sidebar
from lib.ui import show_api_error

st.set_page_config(
    page_title="Asistente IA Educación",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)

init_session()
render_sidebar()

st.title("Asistente IA Educación")
st.caption(
    "Cliente Streamlit de la API JWT. El orquestador y el RAG corren en FastAPI."
)

if is_authenticated():
    user = st.session_state.user or {}
    st.success(f"Sesión activa: **{user.get('email')}** (`{user.get('rol')}`)")
    st.markdown(
        """
Usa el menú lateral:

1. **Conocimiento** — documentos e ingest
2. **Asistente** — nueva petición al orquestador
3. **Historial** — solicitudes anteriores
4. **Aprobaciones** — HITL de exámenes (solo docente)
"""
    )
    st.info("Demo docente: `demo@instituto.local` / `demo1234`")
    st.stop()

tab_login, tab_register = st.tabs(["Iniciar sesión", "Registrarse"])

with tab_login:
    with st.form("login_form"):
        email = st.text_input("Email", value="demo@instituto.local")
        password = st.text_input("Contraseña", type="password", value="demo1234")
        submitted = st.form_submit_button("Entrar", use_container_width=True)
    if submitted:
        try:
            login(email.strip(), password)
            st.rerun()
        except ApiError as exc:
            show_api_error(exc)
        except Exception as exc:
            st.error(f"No se pudo conectar con la API: {exc}")

with tab_register:
    with st.form("register_form"):
        email_r = st.text_input("Email", key="reg_email")
        password_r = st.text_input("Contraseña (≥6)", type="password", key="reg_pw")
        rol = st.selectbox("Rol", ["docente", "alumno"])
        submitted_r = st.form_submit_button("Crear cuenta", use_container_width=True)
    if submitted_r:
        api = ApiClient()
        try:
            api.register(email_r.strip(), password_r, rol)
            st.success("Cuenta creada. Inicia sesión en la pestaña anterior.")
        except ApiError as exc:
            show_api_error(exc)
        except Exception as exc:
            st.error(f"No se pudo conectar con la API: {exc}")
        finally:
            api.close()
