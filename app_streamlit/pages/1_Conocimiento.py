"""Gestión de la base de conocimiento del usuario."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.api_client import ApiError
from lib.session import INDICES, client, render_sidebar, require_auth
from lib.ui import show_api_error

st.set_page_config(page_title="Conocimiento", page_icon="📚", layout="wide")
require_auth()
render_sidebar()

st.title("Conocimiento")
st.caption("Documentos privados por usuario. Ingest → chunks + embeddings en MySQL.")

indice = st.selectbox("Índice", INDICES)
api = client()

try:
    col_list, col_new = st.columns([1.2, 1])

    with col_new:
        st.subheader("Añadir documento")
        with st.form("new_doc"):
            filename = st.text_input("Nombre de archivo", value="apuntes.txt")
            uploaded = st.file_uploader("Subir .txt / .md (opcional)", type=["txt", "md"])
            content = st.text_area("Contenido", height=220)
            submit = st.form_submit_button("Crear", use_container_width=True)
        if submit:
            text = content
            name = filename.strip() or "documento.txt"
            if uploaded is not None:
                text = uploaded.read().decode("utf-8", errors="replace")
                name = uploaded.name or name
            if not text.strip():
                st.warning("El contenido no puede estar vacío.")
            else:
                try:
                    doc = api.create_document(indice, name, text)
                    st.success(f"Documento `{doc['id']}` creado ({doc['status']}).")
                    st.rerun()
                except ApiError as exc:
                    show_api_error(exc)

        if st.button("Ingestar pendientes", type="primary", use_container_width=True):
            try:
                result = api.ingest()
                st.success(
                    f"Procesados: {result.get('procesados')} · "
                    f"Errores: {result.get('errores')}"
                )
                with st.expander("Detalle"):
                    st.json(result.get("detalle") or [])
            except ApiError as exc:
                show_api_error(exc)

    with col_list:
        st.subheader(f"Documentos · `{indice}`")
        try:
            docs = api.list_documents(indice=indice)
        except ApiError as exc:
            show_api_error(exc)
            docs = []

        if not docs:
            st.info("No hay documentos en este índice.")
        else:
            for doc in docs:
                with st.expander(
                    f"#{doc['id']} · {doc['filename']} · `{doc['status']}`"
                ):
                    st.write(
                        f"Creado: `{doc.get('created_at')}` · "
                        f"Actualizado: `{doc.get('updated_at')}`"
                    )
                    if doc.get("error_msg"):
                        st.error(doc["error_msg"])

                    c1, c2, c3 = st.columns(3)
                    if c1.button("Ver / editar", key=f"edit_{doc['id']}"):
                        st.session_state[f"editing_{doc['id']}"] = True
                    if c2.button("Reprocesar", key=f"rep_{doc['id']}"):
                        try:
                            out = api.reprocess(doc["id"])
                            st.success(
                                f"Reprocesado: {out.get('chunks')} chunks "
                                f"({out.get('status')})"
                            )
                        except ApiError as exc:
                            show_api_error(exc)
                    if c3.button("Borrar", key=f"del_{doc['id']}"):
                        try:
                            api.delete_document(doc["id"])
                            st.success("Eliminado.")
                            st.rerun()
                        except ApiError as exc:
                            show_api_error(exc)

                    if st.session_state.get(f"editing_{doc['id']}"):
                        try:
                            detail = api.get_document(doc["id"])
                        except ApiError as exc:
                            show_api_error(exc)
                            continue
                        with st.form(f"form_edit_{doc['id']}"):
                            new_name = st.text_input(
                                "Filename", value=detail.get("filename") or ""
                            )
                            new_text = st.text_area(
                                "Contenido",
                                value=detail.get("content_text") or "",
                                height=200,
                            )
                            save = st.form_submit_button("Guardar")
                        if save:
                            try:
                                api.update_document(
                                    doc["id"],
                                    filename=new_name,
                                    content_text=new_text,
                                )
                                st.session_state[f"editing_{doc['id']}"] = False
                                st.success("Actualizado (vuelve a `pending`).")
                                st.rerun()
                            except ApiError as exc:
                                show_api_error(exc)

    st.divider()
    if st.checkbox("Mostrar chunks del índice"):
        try:
            chunks = api.list_chunks(indice=indice)
            st.write(f"{len(chunks)} chunks (máx. API)")
            for ch in chunks[:50]:
                with st.expander(
                    f"chunk #{ch['id']} · doc {ch['document_id']} · pos {ch['position']}"
                ):
                    st.write(ch.get("texto") or "")
        except ApiError as exc:
            show_api_error(exc)
finally:
    api.close()
