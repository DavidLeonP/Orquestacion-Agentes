"""Helpers de UI Streamlit."""

from __future__ import annotations

import time
from typing import Any, Callable

import streamlit as st

from lib.api_client import ApiClient, ApiError
from lib.labels import (
    agent_label,
    node_hint,
    phase_progress,
    status_badge,
    status_label,
)
from lib.session import is_docente, logout


def show_api_error(exc: ApiError) -> None:
    if exc.status_code == 401:
        logout()
        st.error("Sesión expirada. Vuelve a iniciar sesión en Inicio.")
        return
    st.error(f"{exc.detail}")


def confirm_action(label: str, key: str, *, warn: str | None = None) -> bool:
    """Confirmación en dos pasos (checkbox + botón). Devuelve True si confirma."""
    checked = st.checkbox(
        warn or f"Confirmo: {label}",
        key=f"confirm_chk_{key}",
    )
    if not checked:
        return False
    return st.button(label, key=f"confirm_btn_{key}", type="primary")


def _latest_node(events: list[dict[str, Any]]) -> str | None:
    for ev in reversed(events):
        if ev.get("tipo") == "nodo_grafo":
            payload = ev.get("payload") or {}
            nodo = payload.get("nodo")
            if nodo:
                return str(nodo)
        if ev.get("tipo") == "waiting_approval":
            return "aprobacion_docente"
        if ev.get("tipo") == "completed":
            return "finalizar"
    return None


def _step_timeline(events: list[dict[str, Any]]) -> list[str]:
    steps: list[str] = []
    seen: set[str] = set()
    for ev in events:
        tipo = ev.get("tipo")
        if tipo == "nodo_grafo":
            nodo = (ev.get("payload") or {}).get("nodo")
            if not nodo or nodo in seen:
                continue
            seen.add(nodo)
            steps.append(f"✓ {agent_label(nodo)}")
        elif tipo == "waiting_approval" and "waiting_approval" not in seen:
            seen.add("waiting_approval")
            steps.append("✓ Listo para tu revisión")
        elif tipo == "completed" and "completed" not in seen:
            seen.add("completed")
            steps.append("✓ Respuesta lista")
        elif tipo == "failed" and "failed" not in seen:
            seen.add("failed")
            steps.append("✗ La petición falló")
    return steps


def poll_request(
    api: ApiClient,
    request_id: int,
    *,
    interval_s: float = 2.0,
    max_wait_s: float = 600.0,
    terminal: tuple[str, ...] = ("completed", "failed", "waiting_approval"),
) -> dict[str, Any]:
    """Polling amigable hasta estado terminal, con pasos y tiempo transcurrido."""
    started = time.time()
    deadline = started + max_wait_s
    last: dict[str, Any] = {}
    events: list[dict[str, Any]] = []

    st.info(
        "Los agentes pueden tardar **1–2 minutos** (sobre todo al generar un examen). "
        "Verás el progreso abajo; no hace falta recargar."
    )
    status_box = st.status("Arrancando el asistente…", expanded=True)
    with status_box:
        progress = st.progress(0.05, text="Iniciando…")
        phase = st.empty()
        hint = st.empty()
        timeline = st.empty()
        clock = st.empty()

        while time.time() < deadline:
            try:
                last = api.get_request(request_id)
            except ApiError as exc:
                status_box.update(label="Error al consultar la petición", state="error")
                raise exc

            try:
                events = api.events(request_id)
            except ApiError:
                events = []

            status = last.get("status", "?")
            nodo = _latest_node(events) or last.get("agente_destino")
            elapsed = int(time.time() - started)
            pct = phase_progress(nodo if isinstance(nodo, str) else None, status)
            label = f"{agent_label(nodo)} · {elapsed}s"

            progress.progress(pct, text=label)
            phase.markdown(f"**{status_label(status)}** — {agent_label(nodo)}")
            hint.caption(node_hint(nodo if isinstance(nodo, str) else None))
            steps = _step_timeline(events)
            if steps:
                timeline.markdown("\n".join(steps))
            else:
                timeline.caption("Esperando el primer paso del orquestador…")
            clock.caption(f"Tiempo transcurrido: {elapsed} s")

            if status in terminal:
                progress.progress(1.0 if status != "failed" else pct, text=status_label(status))
                if status == "completed":
                    status_box.update(label=f"Completada en {elapsed}s", state="complete")
                elif status == "waiting_approval":
                    status_box.update(
                        label=f"Lista para tu aprobación ({elapsed}s)",
                        state="complete",
                    )
                else:
                    status_box.update(label=f"Falló tras {elapsed}s", state="error")
                return last

            status_box.update(label=label, state="running")
            time.sleep(interval_s)

        status_box.update(label="Tiempo de espera agotado", state="error")
        st.warning(
            "Sigue en proceso en el servidor. Revisa **Historial** o vuelve a abrir "
            "esta petición más tarde."
        )
    return last


def render_request_result(
    req: dict[str, Any],
    *,
    api: ApiClient | None = None,
    show_inline_approve: bool = True,
    key_prefix: str = "",
) -> dict[str, Any] | None:
    """Renderiza resultado. Si hay approve inline, puede devolver el request actualizado."""
    status = req.get("status")
    agente = req.get("agente_destino")
    rid = req.get("id")
    prefix = f"{key_prefix}_" if key_prefix else ""

    st.markdown(f"### {status_badge(status)}")
    st.caption(f"Petición #{rid} · {agent_label(agente)}")

    if status == "completed":
        st.success("Aquí tienes la respuesta")
        st.markdown(req.get("respuesta_final") or "_(sin respuesta)_")
        c1, c2 = st.columns(2)
        if c1.button(
            "Nueva petición",
            key=f"{prefix}new_req_{rid}",
            use_container_width=True,
        ):
            st.session_state.pop("last_request", None)
            st.session_state.pop("last_request_id", None)
            st.session_state["peticion_draft"] = ""
            st.session_state["clear_peticion"] = True
            st.rerun()
        c2.page_link(
            "pages/3_Historial.py",
            label="Ver en Historial →",
            use_container_width=True,
        )
        return None

    if status == "failed":
        st.error(req.get("error") or "Error desconocido")
        return None

    if status == "waiting_approval":
        st.warning(
            "El borrador está listo. Como docente, debes **aprobarlo o rechazarlo** "
            "antes de que quede como respuesta final."
        )
        approval = req.get("approval") or {}
        if approval.get("borrador"):
            with st.expander("Ver borrador del examen", expanded=True):
                st.markdown(approval["borrador"])
        if approval.get("veredicto"):
            with st.expander("Veredicto de la rúbrica", expanded=False):
                st.markdown(approval["veredicto"])

        updated: dict[str, Any] | None = None
        if show_inline_approve and is_docente() and api is not None:
            st.markdown("**Decide aquí**")
            a1, a2 = st.columns(2)
            with a1:
                if confirm_action(
                    "Aprobar y continuar",
                    key=f"{prefix}inline_ok_{rid}",
                    warn="Confirmo que quiero aprobar este borrador",
                ):
                    try:
                        api.approve(int(req["id"]), "si")
                        st.success("Aprobado. Cerrando la petición…")
                        updated = poll_request(api, int(req["id"]))
                        st.session_state["last_request"] = updated
                    except ApiError as exc:
                        show_api_error(exc)
            with a2:
                if confirm_action(
                    "Rechazar",
                    key=f"{prefix}inline_no_{rid}",
                    warn="Confirmo que quiero rechazar este borrador",
                ):
                    try:
                        api.approve(int(req["id"]), "no")
                        st.warning("Rechazado. Cerrando la petición…")
                        updated = poll_request(api, int(req["id"]))
                        st.session_state["last_request"] = updated
                    except ApiError as exc:
                        show_api_error(exc)
            st.page_link(
                "pages/4_Aprobaciones.py",
                label="O ir a Aprobaciones →",
            )
            return updated

        if is_docente():
            st.page_link(
                "pages/4_Aprobaciones.py",
                label="Ir a Aprobaciones para decidir →",
            )
        return None

    if status == "running":
        st.info(
            "Todavía trabajando. Si acabas de enviarla, espera unos segundos o "
            "usa **Seguir progreso** en Historial."
        )
    return None


def safe_call(fn: Callable[[], Any], *, on_error: str = "Error de API") -> Any:
    try:
        return fn()
    except ApiError as exc:
        show_api_error(exc)
        return None
    except Exception as exc:
        st.error(f"{on_error}: {exc}")
        return None
