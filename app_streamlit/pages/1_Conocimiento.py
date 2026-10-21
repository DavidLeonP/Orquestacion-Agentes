"""Gestión de la base de conocimiento del usuario."""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = ROOT.parent
for _p in (ROOT, PROJECT_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from lib.api_client import ApiClient, ApiError
from lib.labels import doc_status_label, indice_hint, indice_label
from lib.session import INDICES, client, get_user, render_sidebar, require_auth
from lib.ui import confirm_action, show_api_error

st.set_page_config(page_title="Conocimiento", page_icon="📚", layout="wide")

_EN_CURSO = {"extracting", "indexing", "pending"}
_PASO = {
    "cola": "En cola",
    "guardado": "Archivo guardado",
    "audio": "Audio",
    "asr": "Transcripción",
    "pdf": "PDF",
    "texto": "Texto",
    "troceo": "Fragmentos",
    "embeddings": "Embeddings",
    "mysql": "MySQL",
    "chroma": "Chroma",
    "listo": "Listo",
    "error": "Error",
}


def _guardar_subida(user_id: int, nombre: str, raw: bytes) -> Path:
    from src.config import DIR_INBOX

    carpeta = DIR_INBOX / str(user_id)
    carpeta.mkdir(parents=True, exist_ok=True)
    seguro = Path(nombre).name or "documento"
    destino = carpeta / f"{uuid4().hex[:10]}_{seguro}"
    destino.write_bytes(raw)
    return destino


def _linea(evento: dict) -> str:
    paso = _PASO.get(evento.get("paso") or "", evento.get("paso") or "paso")
    hora = evento.get("ts") or ""
    return f"`{hora}` **{paso}** — {evento.get('detalle') or ''}"


@st.fragment(run_every=2)
def _panel_vivo(token: str, indice: str) -> None:
    """Progreso de la cola y estado de la colección Chroma. Se refresca solo."""
    api = ApiClient(token=token, timeout=30)
    try:
        docs = api.list_documents(indice=indice)
        chroma = api.chroma_status(indice=indice)
    except ApiError as exc:
        show_api_error(exc)
        return
    finally:
        api.close()

    activos = [d for d in docs if d.get("status") in _EN_CURSO]
    with st.container(border=True):
        st.subheader("Proceso de indexación")
        if activos:
            st.caption(
                "Sigue en el servidor. Esta caja se actualiza sola: extracción, "
                "embeddings y el upsert en Chroma."
            )
        else:
            st.caption("Nada en curso en este tipo de material.")

        visibles = [
            d
            for d in docs
            if d.get("status") != "indexed" or (d.get("metadatos") or {}).get("progreso")
        ]
        if not visibles:
            st.info("Cuando pulses Crear, el avance de cada archivo aparece aquí.")
        for doc in visibles:
            meta = doc.get("metadatos") or {}
            log = meta.get("progreso") or []
            ultimo = log[-1]["detalle"] if log else "sin pasos todavía"
            st.markdown(
                f"**{doc.get('filename') or 'sin nombre'}** · "
                f"{doc_status_label(doc.get('status'))}"
            )
            st.caption(ultimo)
            if doc.get("error_msg"):
                st.error(doc["error_msg"])
            if log:
                with st.expander("Pasos", expanded=doc.get("status") in _EN_CURSO):
                    for evento in log:
                        st.markdown(_linea(evento))
            chroma_doc = meta.get("chroma") or {}
            if chroma_doc:
                if chroma_doc.get("ok"):
                    st.caption(
                        f"Chroma `{chroma_doc.get('coleccion')}` · "
                        f"upsert {chroma_doc.get('upsert')} · "
                        f"{chroma_doc.get('modelo')} · {chroma_doc.get('dims')} dims"
                    )
                else:
                    st.warning(
                        "Chroma no recibió este documento: "
                        + (chroma_doc.get("error") or chroma_doc.get("detalle") or "sin upsert")
                    )

        st.subheader("Chroma")
        if not chroma.get("ok", True):
            st.error(chroma.get("error") or "No se pudo leer Chroma")
        else:
            c1, c2, c3 = st.columns(3)
            c1.metric("En este índice", chroma.get("vectores_indice") or 0)
            c2.metric("De tu usuario", chroma.get("vectores_usuario") or 0)
            c3.metric("En la colección", chroma.get("total_coleccion") or 0)
            st.caption(
                f"Colección `{chroma.get('coleccion')}` · modelo `{chroma.get('modelo')}` · "
                "distancia coseno. MySQL guarda los vectores; Chroma es el índice HNSW "
                "que usa la búsqueda."
            )
            por_doc = chroma.get("por_documento") or []
            if por_doc:
                nombres = {d["id"]: d.get("filename") for d in docs}
                st.dataframe(
                    [
                        {
                            "documento": nombres.get(fila["document_id"], fila["document_id"]),
                            "vectores": fila["vectores"],
                        }
                        for fila in por_doc
                    ],
                    hide_index=True,
                    use_container_width=True,
                )
            else:
                st.caption("Esta colección no tiene vectores tuyos en este índice.")


require_auth()
render_sidebar()

st.title("Conocimiento")
st.caption(
    "Pulsa **Crear** y el archivo queda guardado al momento. La transcripción y la "
    "indexación siguen abajo: no hace falta esperar el vídeo en el formulario."
)

indice_options = {indice_label(i): i for i in INDICES}
indice_ui = st.selectbox(
    "Tipo de material",
    list(indice_options.keys()),
    help="Cada tipo alimenta un índice distinto del asistente.",
)
indice = indice_options[indice_ui]
st.caption(indice_hint(indice))

aviso = st.session_state.pop("kb_notice", None)
if aviso:
    st.success(aviso)

_panel_vivo(st.session_state.get("token") or "", indice)

api = client()
usuario = get_user() or {}

try:
    col_list, col_new = st.columns([1.2, 1])

    with col_new:
        st.subheader("Añadir documentos")
        with st.form("new_doc"):
            filename = st.text_input(
                "Nombre del texto pegado",
                value="apuntes.txt",
                help="Solo se usa si escribes contenido abajo y no subes archivos.",
            )
            uploaded = st.file_uploader(
                "Subir uno o varios .txt / .md / .pdf / vídeos",
                type=["txt", "md", "pdf", "mp4", "mkv", "webm", "mov", "m4v"],
                accept_multiple_files=True,
                help="Se guardan ya y se procesan en segundo plano. Puedes mezclar documentos y vídeos.",
            )
            content = st.text_area("Contenido pegado (opcional)", height=160)
            submit = st.form_submit_button("Crear", use_container_width=True)
        if submit:
            creados: list[str] = []
            fallos: list[str] = []
            if content.strip() and not uploaded:
                try:
                    doc = api.create_document(indice, filename.strip() or "documento.txt", content)
                    api.process_document(doc["id"])
                    creados.append(doc.get("filename") or filename)
                except ApiError as exc:
                    fallos.append(str(exc))
                except Exception as exc:  # noqa: BLE001
                    fallos.append(str(exc))
            elif uploaded:
                items = []
                user_id = usuario.get("id")
                if not user_id:
                    fallos.append("No hay usuario en la sesión. Vuelve a entrar.")
                else:
                    with st.spinner(f"Guardando {len(uploaded)} archivo(s)…"):
                        for item in uploaded:
                            nombre = item.name or "documento"
                            try:
                                destino = _guardar_subida(user_id, nombre, item.getvalue())
                                items.append({"filename": nombre, "path": str(destino)})
                            except Exception as exc:  # noqa: BLE001
                                fallos.append(f"{nombre}: {exc}")
                    if items:
                        try:
                            docs_nuevos = api.start_jobs(indice, items)
                            creados.extend(d.get("filename") or "" for d in docs_nuevos)
                        except ApiError as exc:
                            fallos.append(str(exc))
            else:
                st.warning("Sube al menos un archivo o pega un contenido.")
            for fallo in fallos:
                st.error(fallo)
            if creados and not fallos:
                st.session_state["kb_notice"] = (
                    f"En cola ({len(creados)}): {', '.join(creados)}. "
                    "El avance está en Proceso de indexación."
                )
                st.rerun()
            elif creados:
                st.success(f"En cola: {', '.join(creados)}")

        if st.button("Indexar pendientes", type="primary", use_container_width=True):
            try:
                pendientes = [
                    d for d in api.list_documents(indice=indice) if d.get("status") == "pending"
                ]
                if not pendientes:
                    st.warning(
                        "No hay documentos pendientes. Si ya elegiste archivos, "
                        "pulsa **Crear**: eso los guarda y arranca la indexación."
                    )
                else:
                    for doc in pendientes:
                        api.process_document(doc["id"])
                    st.session_state["kb_notice"] = (
                        f"{len(pendientes)} documento(s) en cola. "
                        "El avance está en Proceso de indexación."
                    )
                    st.rerun()
            except ApiError as exc:
                show_api_error(exc)

    with col_list:
        st.subheader(f"Documentos · {indice_label(indice)}")
        try:
            docs = api.list_documents(indice=indice)
        except ApiError as exc:
            show_api_error(exc)
            docs = []

        if not docs:
            st.info("Aún no hay documentos aquí. Añade el primero a la derecha.")
        else:
            for doc in docs:
                status_txt = doc_status_label(doc.get("status"))
                with st.expander(f"{doc.get('filename') or 'sin nombre'} · {status_txt}"):
                    st.caption(
                        f"#{doc['id']} · Creado: {doc.get('created_at') or '—'} · "
                        f"Actualizado: {doc.get('updated_at') or '—'}"
                    )
                    if doc.get("error_msg"):
                        st.error(doc["error_msg"])
                    ultimo = ((doc.get("metadatos") or {}).get("progreso") or [])[-1:]
                    if ultimo:
                        st.caption(_linea(ultimo[0]))

                    c1, c2 = st.columns(2)
                    if c1.button("Ver / editar", key=f"edit_{doc['id']}"):
                        st.session_state[f"editing_{doc['id']}"] = True
                    if c2.button("Reprocesar", key=f"rep_{doc['id']}"):
                        try:
                            api.process_document(doc["id"])
                            st.success("En cola. El avance está arriba.")
                        except ApiError as exc:
                            show_api_error(exc)

                    st.markdown("**Eliminar**")
                    if confirm_action(
                        "Eliminar documento",
                        key=f"del_{doc['id']}",
                        warn="Confirmo que quiero eliminar este documento",
                    ):
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
                            new_name = st.text_input("Nombre", value=detail.get("filename") or "")
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
                                st.success(
                                    "Actualizado. Pulsa **Indexar pendientes** "
                                    "para aplicar los cambios."
                                )
                                st.rerun()
                            except ApiError as exc:
                                show_api_error(exc)

    st.divider()
    with st.expander("Vista técnica: fragmentos indexados"):
        st.caption("Solo para depuración. No hace falta para usar el asistente.")
        try:
            chunks = api.list_chunks(indice=indice)
            st.write(f"{len(chunks)} fragmentos (máx. API)")
            for ch in chunks[:50]:
                with st.expander(f"#{ch['id']} · doc {ch['document_id']} · pos {ch['position']}"):
                    st.write(ch.get("texto") or "")
        except ApiError as exc:
            show_api_error(exc)
finally:
    api.close()
