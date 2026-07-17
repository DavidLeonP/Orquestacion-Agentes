"""Gestión de sesión Streamlit (JWT + usuario)."""

from __future__ import annotations

from typing import Any

import streamlit as st

from lib.api_client import ApiClient, ApiError
from lib.labels import format_llm_badge

INDICES = ("apuntes", "examenes", "rubricas", "curriculo")

# Definido aquí para no depender de caché de lib.labels en Streamlit
NAV_ITEMS: list[tuple[str, str, str]] = [
    ("Home.py", "Inicio", "🏠"),
    ("pages/1_Conocimiento.py", "Conocimiento", "📚"),
    ("pages/2_Asistente.py", "Asistente", "💬"),
    ("pages/3_Historial.py", "Historial", "📋"),
    ("pages/4_Aprobaciones.py", "Aprobaciones", "✅"),
]


def init_session() -> None:
    if "token" not in st.session_state:
        st.session_state.token = None
    if "user" not in st.session_state:
        st.session_state.user = None
    if "health" not in st.session_state:
        st.session_state.health = None


def is_authenticated() -> bool:
    return bool(st.session_state.get("token"))


def get_user() -> dict[str, Any] | None:
    return st.session_state.get("user")


def is_docente() -> bool:
    user = get_user()
    return bool(user and user.get("rol") == "docente")


def client() -> ApiClient:
    return ApiClient(token=st.session_state.get("token"))


def refresh_health(api: ApiClient | None = None) -> dict[str, Any] | None:
    owns = api is None
    client_ = api or ApiClient(token=st.session_state.get("token"))
    try:
        health = client_.health()
        st.session_state.health = health
        return health
    except Exception:
        return st.session_state.get("health")
    finally:
        if owns:
            client_.close()


def login(email: str, password: str) -> None:
    api = ApiClient()
    try:
        token_data = api.login(email, password)
        token = token_data["access_token"]
        api.token = token
        user = api.me()
        st.session_state.token = token
        st.session_state.user = user
        try:
            st.session_state.health = api.health()
        except Exception:
            st.session_state.health = None
    finally:
        api.close()


def logout() -> None:
    st.session_state.token = None
    st.session_state.user = None
    st.session_state.health = None


def require_auth() -> dict[str, Any]:
    """Exige sesión; si 401, limpia y detiene."""
    init_session()
    if not is_authenticated():
        st.warning("Inicia sesión en **Inicio** para continuar.")
        st.page_link("Home.py", label="Ir a Inicio →")
        st.stop()

    api = client()
    try:
        user = api.me()
        st.session_state.user = user
        if st.session_state.get("health") is None:
            try:
                st.session_state.health = api.health()
            except Exception:
                pass
        return user
    except ApiError as exc:
        if exc.status_code == 401:
            logout()
            st.error("Sesión expirada. Vuelve a iniciar sesión en Inicio.")
            st.stop()
        st.error(exc.detail)
        st.stop()
    finally:
        api.close()


def require_docente() -> dict[str, Any]:
    user = require_auth()
    if user.get("rol") != "docente":
        st.error("Solo docentes pueden usar esta pantalla (aprobación HITL).")
        st.stop()
    return user


def _render_model_panel(health: dict[str, Any] | None) -> None:
    title, detail = format_llm_badge(health)
    st.markdown("**Modelo activo**")
    if health and (health.get("llm") or {}).get("llm_model"):
        st.success(title)
        st.caption(detail)
    else:
        st.warning(title)
        st.caption(detail)


def render_sidebar() -> None:
    init_session()
    # Menú propio: ocultamos el nav multipágina por defecto de Streamlit.
    st.markdown(
        """
        <style>
        [data-testid="stSidebarNav"] { display: none !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    with st.sidebar:
        st.markdown("### Asistente IA")
        user = get_user()

        if user:
            rol = user.get("rol") or "—"
            st.markdown(f"**{user.get('email')}**")
            st.caption(f"Rol: {rol}")

            health = st.session_state.get("health")
            if health is None:
                health = refresh_health()
            _render_model_panel(health)

            st.divider()
            st.markdown("**Menú**")
            for path, label, icon in NAV_ITEMS:
                if path.endswith("4_Aprobaciones.py") and not is_docente():
                    continue
                st.page_link(path, label=f"{icon} {label}", use_container_width=True)

            st.divider()
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Actualizar modelo", use_container_width=True):
                    refresh_health()
                    st.rerun()
            with c2:
                if st.button("Salir", use_container_width=True):
                    logout()
                    st.rerun()
        else:
            st.caption("Inicia sesión para usar el asistente.")
            health = st.session_state.get("health")
            if health is None:
                health = refresh_health()
            _render_model_panel(health)
