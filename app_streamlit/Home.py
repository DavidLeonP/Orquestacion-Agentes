"""Asistente IA Educación — UI Streamlit (cliente de la API JWT)."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.api_client import ApiClient, ApiError
from lib.labels import format_llm_badge
from lib.session import (
    init_session,
    is_authenticated,
    is_docente,
    login,
    render_sidebar,
)
from lib.ui import show_api_error

# Menú local (evita ImportError por caché de módulos en Streamlit)
NAV_ITEMS = [
    ("Home.py", "Inicio", "🏠"),
    ("pages/1_Conocimiento.py", "Conocimiento", "📚"),
    ("pages/2_Asistente.py", "Asistente", "💬"),
    ("pages/3_Historial.py", "Historial", "📋"),
    ("pages/4_Aprobaciones.py", "Aprobaciones", "✅"),
]

st.set_page_config(
    page_title="Asistente IA Educación",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)

init_session()
render_sidebar()

if is_authenticated():
    user = st.session_state.user or {}
    health = st.session_state.get("health")
    model_title, model_detail = format_llm_badge(health)

    st.title("Bienvenido")
    st.markdown(
        f"Sesión de **{user.get('email')}** · rol `{user.get('rol')}`"
    )

    m1, m2 = st.columns([1.2, 1])
    with m1:
        st.subheader("Modelo activo")
        if health and (health.get("llm") or {}).get("llm_model"):
            st.success(model_title)
            st.caption(model_detail)
        else:
            st.warning(model_title)
            st.caption(model_detail)
    with m2:
        st.subheader("¿Qué quieres hacer?")
        st.caption("Elige una sección del menú:")

    st.divider()
    cols = st.columns(2)
    links = [
        item
        for item in NAV_ITEMS
        if item[0] != "Home.py"
        and not (item[0].endswith("4_Aprobaciones.py") and not is_docente())
    ]
    descriptions = {
        "pages/1_Conocimiento.py": "Sube y gestiona apuntes, exámenes y rúbricas.",
        "pages/2_Asistente.py": "Haz una pregunta o pide generar material.",
        "pages/3_Historial.py": "Revisa peticiones anteriores y su resultado.",
        "pages/4_Aprobaciones.py": "Aprueba o rechaza borradores de examen.",
    }
    for i, (path, label, icon) in enumerate(links):
        with cols[i % 2]:
            with st.container(border=True):
                st.markdown(f"#### {icon} {label}")
                st.caption(descriptions.get(path, ""))
                st.page_link(path, label=f"Abrir {label} →", use_container_width=True)

    st.stop()

st.title("Asistente IA Educación")
st.caption("Inicia sesión para usar el orquestador multi-agente y tu base de conocimiento.")

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
    st.caption("Demo docente: `demo@instituto.local` / `demo1234`")

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
