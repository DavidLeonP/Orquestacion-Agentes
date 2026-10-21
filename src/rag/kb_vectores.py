"""Índice vectorial de la KB en Chroma (VECTOR_BACKEND=chroma).

MySQL (`chunk_embeddings`) es la fuente de verdad. Chroma es un índice HNSW
derivado: si le faltan vectores (primer arranque, fallo al indexar), `sincronizar`
los copia desde MySQL sin volver a llamar al modelo de embeddings.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from src.db.models import Chunk, ChunkEmbedding
from src.llm import active_embedding_model
from src.rag.chroma_client import coleccion_vectores, filtro, id_vector

logger = logging.getLogger("orquestacion.rag")


def _kb():
    return coleccion_vectores("kb")


def upsert(chunks: list[Chunk], vectores: list[list[float]]) -> str:
    """Inserta o actualiza vectores. Devuelve el nombre de la colección."""
    col = _kb()
    if not chunks:
        return col.name
    col.upsert(
        ids=[id_vector(c.user_id, c.chunk_uid) for c in chunks],
        embeddings=vectores,
        metadatas=[
            {"user_id": c.user_id, "indice": c.indice, "document_id": c.document_id,
             "chunk_uid": c.chunk_uid}
            for c in chunks
        ],
    )
    return col.name


def borrar_documento(document_id: int) -> None:
    try:
        _kb().delete(where=filtro(document_id=document_id))
    except Exception as exc:  # noqa: BLE001 - sincronizar() no resucita borrados, pero no rompe la API
        logger.warning("Chroma: no se pudieron borrar vectores de document_id=%s: %s", document_id, exc)


def sincronizar(
    db: Session, user_id: int, indice: str, chunk_uids: list[str], forzar: bool = False
) -> int:
    """Copia a Chroma los vectores de MySQL que le falten (o todos con `forzar`)."""
    if not chunk_uids:
        return 0
    presentes = set() if forzar else set(
        _kb().get(where=filtro(user_id=user_id, indice=indice), include=[])["ids"]
    )
    faltan = [u for u in chunk_uids if id_vector(user_id, u) not in presentes]
    if not faltan:
        return 0
    filas = (
        db.query(Chunk, ChunkEmbedding.embedding)
        .join(ChunkEmbedding, ChunkEmbedding.chunk_id == Chunk.id)
        .filter(
            Chunk.user_id == user_id,
            Chunk.indice == indice,
            Chunk.chunk_uid.in_(faltan),
            ChunkEmbedding.model == active_embedding_model(),
        )
        .all()
    )
    if not filas:
        logger.warning("Sin embeddings del modelo '%s' para user=%s indice=%s; solo BM25. "
                       "Reprocesa la KB si quieres búsqueda semántica.",
                       active_embedding_model(), user_id, indice)
        return 0
    upsert([c for c, _ in filas], [e for _, e in filas])
    logger.info("Chroma: %d vectores sincronizados desde MySQL (user=%s indice=%s)",
                len(filas), user_id, indice)
    return len(filas)


def estado(user_id: int, indice: str | None = None) -> dict:
    """Resumen de la colección activa: cuántos vectores hay y de qué documento."""
    col = _kb()
    modelo = active_embedding_model()
    try:
        total = col.count()
        got = col.get(where=filtro(user_id=user_id), include=["metadatas"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("Chroma: no se pudo leer el estado (user=%s): %s", user_id, exc)
        return {
            "ok": False,
            "coleccion": col.name,
            "modelo": modelo,
            "espacio": "cosine",
            "error": str(exc)[:500],
        }
    metas = got.get("metadatas") or []
    ids = got.get("ids") or []
    if indice:
        metas_indice = [m for m in metas if (m or {}).get("indice") == indice]
    else:
        metas_indice = list(metas)
    por_doc: dict[int, int] = {}
    for meta in metas_indice:
        did = int((meta or {}).get("document_id") or 0)
        por_doc[did] = por_doc.get(did, 0) + 1
    return {
        "ok": True,
        "coleccion": col.name,
        "modelo": modelo,
        "espacio": "cosine",
        "total_coleccion": total,
        "vectores_usuario": len(ids),
        "vectores_indice": len(metas_indice),
        "indice": indice,
        "por_documento": [
            {"document_id": did, "vectores": n} for did, n in sorted(por_doc.items())
        ],
    }


def buscar(user_id: int, indice: str, vector: list[float], k: int) -> list[str]:
    """chunk_uid de los k vecinos más cercanos, en orden."""
    res = _kb().query(
        query_embeddings=[vector],
        n_results=k,
        where=filtro(user_id=user_id, indice=indice),
        include=["metadatas"],
    )
    return [m["chunk_uid"] for m in res["metadatas"][0]]
