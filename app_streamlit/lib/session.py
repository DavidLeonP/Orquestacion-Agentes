"""Gestión de sesión Streamlit (JWT + usuario)."""

from __future__ import annotations

from typing import Any

import streamlit as st

from lib.api_client import ApiClient, ApiError

INDICES = ("apuntes", "examenes", "rubricas", "curriculo")


def init_session() -> None:
    if "token" not in st.session_state:
        st.session_state.token = None
    if "user" not in st.session_state:
        st.session_state.user = None


def is_authenticated() -> bool:
    return bool(st.session_state.get("token"))


def get_user() -> dict[str, Any] | None:
    return st.session_state.get("user")


def is_docente() -> bool:
    user = get_user()
    return bool(user and user.get("rol") == "docente")


def client() -> ApiClient:
    return ApiClient(token=st.session_state.get("token"))


def login(email: str, password: str) -> None:
    api = ApiClient()
    try:
        token_data = api.login(email, password)
        token = token_data["access_token"]
        api.token = token
        user = api.me()
        st.session_state.token = token
        st.session_state.user = user
    finally:
        api.close()


def logout() -> None:
    st.session_state.token = None
    st.session_state.user = None


def require_auth() -> dict[str, Any]:
    """Exige sesión; si 401, limpia y detiene."""
    init_session()
    if not is_authenticated():
        st.warning("Inicia sesión en **Home** para continuar.")
        st.stop()

    api = client()
    try:
        user = api.me()
        st.session_state.user = user
        return user
    except ApiError as exc:
        if exc.status_code == 401:
            logout()
            st.error("Sesión expirada. Vuelve a iniciar sesión en Home.")
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


def render_sidebar() -> None:
    init_session()
    with st.sidebar:
        st.caption("Asistente IA Educación")
        user = get_user()
        if user:
            st.markdown(f"**{user.get('email')}**")
            st.caption(f"Rol: `{user.get('rol')}`")
            if st.button("Cerrar sesión", use_container_width=True):
                logout()
                st.rerun()
        else:
            st.caption("Sin sesión")

        api = ApiClient(token=st.session_state.get("token"))
        try:
            health = api.health()
            llm = health.get("llm") or {}
            st.divider()
            st.caption("Modelo activo")
            st.code(
                f"profile: {llm.get('profile', '?')}\n"
                f"llm: {llm.get('llm_provider')}/{llm.get('llm_model')}\n"
                f"emb: {llm.get('embedding_provider')}/{llm.get('embedding_model')}",
                language=None,
            )
        except Exception:
            st.caption("API no disponible (`/health`)")
        finally:
            api.close()
