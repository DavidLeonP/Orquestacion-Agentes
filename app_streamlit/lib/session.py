"""Gestión de sesión Streamlit (JWT + usuario)."""

from __future__ import annotations

from typing import Any

import streamlit as st

from lib.api_client import ApiClient, ApiError
from lib.labels import NAV_ITEMS, format_llm_badge

INDICES = ("apuntes", "examenes", "rubricas", "curriculo")


def init_session() -> None:
    if "token" not in st.session_state:
        st.session_state.token = None
    if "user" not in st.session_state:
        st.session_state.user = None
    if "health" not in st.session_state:
        st.session_state.health = None
    if "pending_approvals" not in st.session_state:
        st.session_state.pending_approvals = None


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


def refresh_pending_approvals(api: ApiClient | None = None) -> int:
    """Cuenta solicitudes waiting_approval del usuario (docente)."""
    if not is_docente():
        st.session_state.pending_approvals = 0
        return 0
    owns = api is None
    client_ = api or client()
    try:
        reqs = client_.list_requests()
        n = sum(1 for r in reqs if r.get("status") == "waiting_approval")
        st.session_state.pending_approvals = n
        return n
    except Exception:
        return int(st.session_state.get("pending_approvals") or 0)
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
        if user.get("rol") == "docente":
            refresh_pending_approvals(api)
        else:
            st.session_state.pending_approvals = 0
    finally:
        api.close()


def logout() -> None:
    st.session_state.token = None
    st.session_state.user = None
    st.session_state.health = None
    st.session_state.pending_approvals = None


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
        if user.get("rol") == "docente" and st.session_state.get("pending_approvals") is None:
            refresh_pending_approvals(api)
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
    if health and (health.get("llm") or {}).get("llm_model"):
        st.caption(f"Modelo: **{title}**")
        st.caption(detail)
    else:
        st.caption(f"Modelo: {title}")
        st.caption(detail)


def render_sidebar() -> None:
    init_session()
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

            pending = st.session_state.get("pending_approvals")
            if is_docente() and pending is None:
                pending = refresh_pending_approvals()

            st.divider()
            st.markdown("**Menú**")
            for path, label, icon in NAV_ITEMS:
                if path.endswith("4_Aprobaciones.py") and not is_docente():
                    continue
                nav_label = f"{icon} {label}"
                if path.endswith("4_Aprobaciones.py") and pending:
                    nav_label = f"{icon} {label} ({pending})"
                st.page_link(path, label=nav_label, use_container_width=True)

            st.divider()
            if st.button("Salir", use_container_width=True):
                logout()
                st.rerun()
        else:
            st.caption("Inicia sesión para usar el asistente.")
            health = st.session_state.get("health")
            if health is None:
                health = refresh_health()
            _render_model_panel(health)
