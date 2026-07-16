"""Historial de solicitudes del usuario."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.api_client import ApiError
from lib.session import client, render_sidebar, require_auth
from lib.ui import render_request_result, show_api_error

st.set_page_config(page_title="Historial", page_icon="📋", layout="wide")
require_auth()
render_sidebar()

st.title("Historial")
st.caption("Últimas solicitudes del usuario autenticado.")

api = client()
try:
    if st.button("Actualizar", use_container_width=False):
        st.rerun()

    try:
        requests = api.list_requests()
    except ApiError as exc:
        show_api_error(exc)
        requests = []

    if not requests:
        st.info("Aún no hay solicitudes.")
        st.stop()

    rows = [
        {
            "id": r["id"],
            "status": r["status"],
            "agente": r.get("agente_destino") or "—",
            "peticion": (r.get("peticion") or "")[:80],
            "updated_at": r.get("updated_at"),
        }
        for r in requests
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)

    for r in requests:
        label = (
            f"#{r['id']} · `{r['status']}` · "
            f"{(r.get('peticion') or '')[:60]}"
        )
        with st.expander(label):
            render_request_result(r)
            if st.button("Cargar eventos", key=f"ev_{r['id']}"):
                try:
                    events = api.events(r["id"])
                    st.json(events)
                except ApiError as exc:
                    show_api_error(exc)
finally:
    api.close()
