"""Pipeline de ingesta hacia MySQL (chunks + embeddings por usuario)."""

from __future__ import annotations

import re

from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy.orm import Session

from src.config import EMBEDDING_MODEL
from src.db.models import Chunk, ChunkEmbedding, Document
from src.rag.mysql_store import invalidar_cache_retriever

CABECERA_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


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


def indexar_documento(db: Session, doc: Document) -> int:
    """Trocea, embebe y persiste chunks del documento. Devuelve nº de chunks."""
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
    embedder = OpenAIEmbeddings(model=EMBEDDING_MODEL)

    meta_base = dict(doc.metadatos or {})
    meta_base.setdefault("fuente", doc.filename)
    parsed_meta, cuerpo = extraer_metadatos(doc.content_text, doc.filename)
    meta = {**parsed_meta, **meta_base}

    _borrar_chunks_documento(db, doc.id)

    trozos = splitter.split_text(cuerpo) or [cuerpo]
    embeddings = embedder.embed_documents(trozos) if trozos else []

    for i, (texto, emb) in enumerate(zip(trozos, embeddings)):
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
        db.add(
            ChunkEmbedding(
                chunk_id=chunk.id,
                model=EMBEDDING_MODEL,
                dims=len(emb),
                embedding=emb,
            )
        )

    doc.status = "indexed"
    doc.error_msg = None
    doc.metadatos = meta
    db.commit()
    invalidar_cache_retriever(doc.user_id)
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
