"""Helpers de UI Streamlit."""

from __future__ import annotations

import time
from typing import Any, Callable

import streamlit as st

from lib.api_client import ApiClient, ApiError
from lib.session import logout


def show_api_error(exc: ApiError) -> None:
    if exc.status_code == 401:
        logout()
        st.error("Sesión expirada. Vuelve a iniciar sesión en Home.")
        return
    st.error(f"{exc.detail}")


def poll_request(
    api: ApiClient,
    request_id: int,
    *,
    interval_s: float = 2.0,
    max_wait_s: float = 600.0,
    terminal: tuple[str, ...] = ("completed", "failed", "waiting_approval"),
) -> dict[str, Any]:
    """Polling de GET /requests/{id} hasta estado terminal."""
    deadline = time.time() + max_wait_s
    last: dict[str, Any] = {}
    status_box = st.status("Procesando solicitud…", expanded=True)
    with status_box:
        while time.time() < deadline:
            try:
                last = api.get_request(request_id)
            except ApiError as exc:
                status_box.update(label="Error al consultar", state="error")
                raise exc
            status = last.get("status", "?")
            agente = last.get("agente_destino") or "—"
            st.write(f"Estado: `{status}` · Agente: `{agente}`")
            if status in terminal:
                if status == "completed":
                    status_box.update(label="Completado", state="complete")
                elif status == "waiting_approval":
                    status_box.update(label="Esperando aprobación", state="complete")
                else:
                    status_box.update(label="Falló", state="error")
                return last
            time.sleep(interval_s)
        status_box.update(label="Tiempo de espera agotado", state="error")
    return last


def render_request_result(req: dict[str, Any]) -> None:
    status = req.get("status")
    st.markdown(f"**Request** `{req.get('id')}` · thread `{req.get('thread_id')}`")
    st.caption(f"Estado: `{status}` · Agente: `{req.get('agente_destino') or '—'}`")

    if status == "completed":
        st.success("Respuesta lista")
        st.markdown(req.get("respuesta_final") or "_(sin respuesta)_")
    elif status == "failed":
        st.error(req.get("error") or "Error desconocido")
    elif status == "waiting_approval":
        st.warning(
            "Pendiente de aprobación docente. Ve a la página **Aprobaciones**."
        )
        approval = req.get("approval") or {}
        if approval.get("borrador"):
            with st.expander("Borrador", expanded=True):
                st.markdown(approval["borrador"])
        if approval.get("veredicto"):
            with st.expander("Veredicto rúbrica"):
                st.markdown(approval["veredicto"])
    elif status == "running":
        st.info("Aún en proceso…")


def safe_call(fn: Callable[[], Any], *, on_error: str = "Error de API") -> Any:
    try:
        return fn()
    except ApiError as exc:
        show_api_error(exc)
        return None
    except Exception as exc:
        st.error(f"{on_error}: {exc}")
        return None
