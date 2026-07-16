"""Aprobación HITL de exámenes (solo docentes)."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.api_client import ApiError
from lib.session import client, render_sidebar, require_docente
from lib.ui import poll_request, render_request_result, show_api_error

st.set_page_config(page_title="Aprobaciones", page_icon="✅", layout="wide")
require_docente()
render_sidebar()

st.title("Aprobaciones")
st.caption("Human-in-the-loop: revisar borrador de examen y aprobar o rechazar.")

api = client()
try:
    if st.button("Actualizar lista"):
        st.rerun()

    try:
        all_reqs = api.list_requests()
    except ApiError as exc:
        show_api_error(exc)
        all_reqs = []

    pending = [r for r in all_reqs if r.get("status") == "waiting_approval"]

    if not pending:
        st.info("No hay solicitudes pendientes de aprobación.")
        st.stop()

    for req in pending:
        with st.container(border=True):
            st.markdown(
                f"### Request `{req['id']}` · `{req.get('agente_destino') or '—'}`"
            )
            st.write(req.get("peticion") or "")

            approval = req.get("approval")
            if not approval:
                try:
                    detail = api.get_request(req["id"])
                    approval = detail.get("approval")
                    req = detail
                except ApiError as exc:
                    show_api_error(exc)
                    continue

            if approval:
                with st.expander("Borrador", expanded=True):
                    st.markdown(approval.get("borrador") or "_(vacío)_")
                with st.expander("Veredicto"):
                    st.markdown(approval.get("veredicto") or "_(vacío)_")
            else:
                st.warning("Sin payload de aprobación todavía.")

            c1, c2 = st.columns(2)
            if c1.button("Aprobar", type="primary", key=f"ok_{req['id']}"):
                try:
                    api.approve(req["id"], "si")
                    st.success("Aprobado. Continuando…")
                    result = poll_request(api, req["id"])
                    render_request_result(result)
                except ApiError as exc:
                    show_api_error(exc)
            if c2.button("Rechazar", key=f"no_{req['id']}"):
                try:
                    api.approve(req["id"], "no")
                    st.warning("Rechazado. Continuando…")
                    result = poll_request(api, req["id"])
                    render_request_result(result)
                except ApiError as exc:
                    show_api_error(exc)
finally:
    api.close()
