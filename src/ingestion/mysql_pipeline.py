"""Pipeline de ingesta hacia MySQL (chunks + embeddings por usuario) y Chroma."""

from __future__ import annotations

import logging
import re

from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from src.db.models import Chunk, ChunkEmbedding, Document
from src.config import VECTOR_BACKEND
from src.llm import active_embedding_model, get_embeddings
from src.rag import kb_vectores
from src.rag.mysql_store import invalidar_cache_retriever

logger = logging.getLogger("orquestacion.ingesta")

CABECERA_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
_CLAVES_INTERNAS = frozenset({"progreso", "paso", "chroma", "storage_path"})
_LOTE_EMBEDDINGS = 8


def extraer_metadatos(texto: str, filename: str) -> tuple[dict, str]:
    metadatos = {"fuente": filename}
    match = CABECERA_RE.match(texto)
    if not match:
        return metadatos, texto
    for linea in match.group(1).splitlines():
        if ":" in linea:
            clave, valor = linea.split(":", 1)
            metadatos[clave.strip()] = valor.strip()
    return metadatos, texto[match.end() :]


def _borrar_chunks_documento(db: Session, document_id: int) -> None:
    chunks = db.query(Chunk).filter(Chunk.document_id == document_id).all()
    for c in chunks:
        db.delete(c)
    db.flush()
    kb_vectores.borrar_documento(document_id)


def indexar_documento(db: Session, doc: Document, on_step=None) -> int:
    """Trocea, embebe y persiste chunks del documento. Devuelve nº de chunks.

    `on_step(paso, detalle)` se llama en el troceo, en cada lote de embeddings
    y al cerrar el upsert en Chroma. Puede hacer commit: por eso los pasos de
    embedding ocurren antes de tocar las filas de chunks.
    """
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
    embedder = get_embeddings()
    emb_model = active_embedding_model()

    meta_base = {
        k: v for k, v in dict(doc.metadatos or {}).items() if k not in _CLAVES_INTERNAS
    }
    meta_base.setdefault("fuente", doc.filename)
    parsed_meta, cuerpo = extraer_metadatos(doc.content_text or "", doc.filename)
    meta = {**parsed_meta, **meta_base}

    trozos = splitter.split_text(cuerpo) or [cuerpo]
    if on_step:
        on_step("troceo", f"{len(trozos)} fragmentos")

    embeddings: list[list[float]] = []
    for inicio in range(0, len(trozos), _LOTE_EMBEDDINGS):
        lote = trozos[inicio : inicio + _LOTE_EMBEDDINGS]
        vectores = embedder.embed_documents(lote) if lote else []
        if len(vectores) != len(lote):
            raise RuntimeError(
                f"El modelo devolvió {len(vectores)} vectores para {len(lote)} fragmentos"
            )
        embeddings.extend(vectores)
        if on_step and embeddings:
            on_step(
                "embeddings",
                f"{len(embeddings)}/{len(trozos)} · {emb_model} · {len(embeddings[-1])} dims",
            )

    _borrar_chunks_documento(db, doc.id)

    nuevos = []
    for i, texto in enumerate(trozos):
        emb = embeddings[i]
        chunk = Chunk(
            document_id=doc.id,
            user_id=doc.user_id,
            indice=doc.indice,
            chunk_uid=f"{doc.id}-{doc.filename}-{i}",
            texto=texto,
            metadatos=meta,
            position=i,
        )
        db.add(chunk)
        db.flush()
        nuevos.append(chunk)
        db.add(
            ChunkEmbedding(
                chunk_id=chunk.id,
                model=emb_model,
                dims=len(emb),
                embedding=emb,
            )
        )

    if VECTOR_BACKEND == "chroma":
        try:
            coleccion = kb_vectores.upsert(nuevos, embeddings)
            chroma_info = {
                "ok": True,
                "coleccion": coleccion,
                "upsert": len(nuevos),
                "modelo": emb_model,
                "dims": len(embeddings[0]) if embeddings else 0,
            }
        except Exception as exc:  # noqa: BLE001 - el retriever los resincroniza desde MySQL
            logger.warning("Chroma: indexación diferida de document_id=%s: %s", doc.id, exc)
            chroma_info = {"ok": False, "error": str(exc)[:500], "modelo": emb_model}
    else:
        chroma_info = {
            "ok": False,
            "omitido": True,
            "detalle": f"VECTOR_BACKEND={VECTOR_BACKEND}",
            "modelo": emb_model,
        }

    final = dict(doc.metadatos or {})
    final.update(meta)
    final["chroma"] = chroma_info
    doc.metadatos = final
    flag_modified(doc, "metadatos")
    doc.status = "indexed"
    doc.error_msg = None
    db.commit()
    invalidar_cache_retriever(doc.user_id)
    if on_step:
        on_step("mysql", f"{len(nuevos)} fragmentos y embeddings en MySQL")
        if chroma_info.get("ok"):
            on_step(
                "chroma",
                f"upsert {chroma_info['upsert']} vectores en {chroma_info['coleccion']}",
            )
        else:
            on_step(
                "chroma",
                chroma_info.get("error") or chroma_info.get("detalle") or "sin upsert",
            )
    return len(trozos)


def ingest_pendientes(db: Session, user_id: int) -> dict:
    docs = (
        db.query(Document)
        .filter(Document.user_id == user_id, Document.status == "pending")
        .all()
    )
    detalle = []
    errores = 0
    for doc in docs:
        try:
            n = indexar_documento(db, doc)
            detalle.append({"document_id": doc.id, "filename": doc.filename, "chunks": n})
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            doc = db.get(Document, doc.id)
            if doc:
                doc.status = "error"
                doc.error_msg = str(exc)[:2000]
                db.commit()
            errores += 1
            detalle.append({"document_id": doc.id if doc else None, "error": str(exc)})
    return {"procesados": len(detalle) - errores, "errores": errores, "detalle": detalle}


def reprocess_documento(db: Session, user_id: int, document_id: int) -> dict:
    doc = (
        db.query(Document)
        .filter(Document.id == document_id, Document.user_id == user_id)
        .first()
    )
    if doc is None:
        raise LookupError("Documento no encontrado")
    doc.status = "pending"
    db.commit()
    try:
        n = indexar_documento(db, doc)
        return {"document_id": doc.id, "chunks": n, "status": doc.status}
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        doc = db.get(Document, document_id)
        if doc:
            doc.status = "error"
            doc.error_msg = str(exc)[:2000]
            db.commit()
        raise
