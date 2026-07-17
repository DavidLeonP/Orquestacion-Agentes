"""Historial de solicitudes del usuario."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.api_client import ApiError
from lib.labels import agent_label, status_label
from lib.session import client, render_sidebar, require_auth
from lib.ui import render_request_result, show_api_error

st.set_page_config(page_title="Historial", page_icon="📋", layout="wide")
require_auth()
render_sidebar()

st.title("Historial")
st.caption("Tus peticiones recientes y su estado.")

api = client()
try:
    if st.button("Actualizar lista"):
        st.rerun()

    try:
        requests = api.list_requests()
    except ApiError as exc:
        show_api_error(exc)
        requests = []

    if not requests:
        st.info("Aún no hay peticiones. Ve a **Asistente** para crear la primera.")
        st.page_link("pages/2_Asistente.py", label="Ir al Asistente →")
        st.stop()

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

    for r in requests:
        label = (
            f"#{r['id']} · {status_label(r.get('status'))} · "
            f"{(r.get('peticion') or '')[:60]}"
        )
        with st.expander(label):
            render_request_result(r)
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
