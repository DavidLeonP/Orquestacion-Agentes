"""Historial de solicitudes del usuario."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.api_client import ApiError
from lib.labels import agent_label, status_badge, status_label
from lib.session import client, is_docente, refresh_pending_approvals, render_sidebar, require_auth
from lib.ui import poll_request, render_request_result, show_api_error

st.set_page_config(page_title="Historial", page_icon="📋", layout="wide")
require_auth()
render_sidebar()

st.title("Historial")
st.caption("Tus peticiones recientes y su estado.")

FILTERS = {
    "Todas": None,
    "En proceso": "running",
    "Pendiente de aprobación": "waiting_approval",
    "Completada": "completed",
    "Falló": "failed",
}

api = client()
try:
    top = st.columns([3, 1])
    with top[0]:
        filtro = st.selectbox("Filtrar por estado", list(FILTERS.keys()))
    with top[1]:
        if st.button("Actualizar lista", use_container_width=True):
            if is_docente():
                refresh_pending_approvals(api)
            st.rerun()

    try:
        requests = api.list_requests()
    except ApiError as exc:
        show_api_error(exc)
        requests = []

    status_filter = FILTERS[filtro]
    if status_filter:
        requests = [r for r in requests if r.get("status") == status_filter]

    if not requests:
        st.info("No hay peticiones con este filtro. Ve al **Asistente** para crear una.")
        st.page_link("pages/2_Asistente.py", label="Ir al Asistente →")
        st.stop()

    actionable = [
        r
        for r in requests
        if r.get("status") in {"running", "waiting_approval"}
    ]
    if actionable and filtro == "Todas":
        st.subheader("Requieren atención")
        for r in actionable:
            with st.container(border=True):
                st.markdown(
                    f"**#{r['id']}** · {status_badge(r.get('status'))} · "
                    f"{agent_label(r.get('agente_destino'))}"
                )
                st.caption((r.get("peticion") or "")[:120])
                b1, b2 = st.columns(2)
                if r.get("status") == "running":
                    if b1.button(
                        "Seguir progreso",
                        key=f"resume_{r['id']}",
                        type="primary",
                        use_container_width=True,
                    ):
                        try:
                            result = poll_request(api, r["id"])
                            st.session_state["last_request"] = result
                            render_request_result(
                                result, api=api, key_prefix=f"hist_resume_{r['id']}"
                            )
                            if is_docente():
                                refresh_pending_approvals(api)
                        except ApiError as exc:
                            show_api_error(exc)
                elif r.get("status") == "waiting_approval" and is_docente():
                    b1.page_link(
                        "pages/4_Aprobaciones.py",
                        label="Ir a Aprobaciones →",
                        use_container_width=True,
                    )
                    if b2.button(
                        "Ver detalle aquí",
                        key=f"det_{r['id']}",
                        use_container_width=True,
                    ):
                        try:
                            detail = api.get_request(r["id"])
                            render_request_result(
                                detail,
                                api=api,
                                key_prefix=f"hist_attn_{r['id']}",
                            )
                        except ApiError as exc:
                            show_api_error(exc)
        st.divider()

    rows = [
        {
            "Nº": r["id"],
            "Estado": status_label(r.get("status")),
            "Agente": agent_label(r.get("agente_destino")),
            "Petición": (r.get("peticion") or "")[:100],
            "Actualizada": r.get("updated_at"),
        }
        for r in requests
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)

    st.subheader("Detalle")
    for r in requests:
        label = (
            f"#{r['id']} · {status_badge(r.get('status'))} · "
            f"{(r.get('peticion') or '')[:60]}"
        )
        with st.expander(label):
            try:
                detail = api.get_request(r["id"])
            except ApiError:
                detail = r
            render_request_result(
                detail,
                api=api,
                show_inline_approve=is_docente(),
                key_prefix=f"hist_exp_{r['id']}",
            )
            if st.button("Ver pasos del proceso", key=f"ev_{r['id']}"):
                try:
                    events = api.events(r["id"])
                    if not events:
                        st.caption("Sin eventos registrados.")
                    else:
                        for ev in events:
                            tipo = ev.get("tipo")
                            if tipo == "nodo_grafo":
                                nodo = (ev.get("payload") or {}).get("nodo")
                                st.write(f"• {agent_label(nodo)}")
                            elif tipo == "waiting_approval":
                                st.write("• Pendiente de aprobación docente")
                            elif tipo == "completed":
                                st.write("• Completada")
                            elif tipo == "failed":
                                err = (ev.get("payload") or {}).get("error", "")
                                st.write(f"• Falló: {err}")
                            else:
                                st.write(f"• {tipo}")
                except ApiError as exc:
                    show_api_error(exc)
finally:
    api.close()
