"""Retriever híbrido de la KB por usuario: BM25 + embeddings + RRF.

El ranking semántico sale de Chroma (VECTOR_BACKEND=chroma, HNSW) o del coseno
en Python sobre `chunk_embeddings` (VECTOR_BACKEND=mysql, legado).
"""

from __future__ import annotations

import logging
from functools import lru_cache

import numpy as np
from rank_bm25 import BM25Okapi
from sqlalchemy.orm import Session, joinedload

from src.config import VECTOR_BACKEND
from src.db.models import Chunk
from src.db.session import SessionLocal
from src.llm import active_embedding_model, get_embeddings
from src.rag import kb_vectores
from src.rag.rrf import fusion_rrf, ranking_bm25, tokenizar  # tokenizar: BM25 score en buscar_con_score

logger = logging.getLogger("orquestacion.rag")


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


class RetrieverHibridoMySQL:
    def __init__(self, user_id: int, indice: str, db: Session | None = None):
        self.user_id = user_id
        self.indice = indice
        self._own_session = db is None
        self.db = db or SessionLocal()
        self.backend = VECTOR_BACKEND
        self.chunks: list[dict] = []
        self._embeddings: dict[str, list[float]] = {}
        self._embedder = get_embeddings()
        try:
            self._cargar()
        finally:
            # La búsqueda no vuelve a tocar MySQL: se libera la conexión para que los
            # retrievers en caché no retengan el pool ni mueran por inactividad.
            self.close()

    def _cargar(self) -> None:
        query = self.db.query(Chunk).filter(
            Chunk.user_id == self.user_id, Chunk.indice == self.indice
        )
        if self.backend == "mysql":
            query = query.options(joinedload(Chunk.embedding))
        rows = query.order_by(Chunk.position).all()
        self.chunks = [
            {"id": c.chunk_uid, "texto": c.texto, "metadatos": c.metadatos or {}} for c in rows
        ]
        self.bm25 = BM25Okapi([tokenizar(c["texto"]) for c in self.chunks]) if self.chunks else None

        if self.backend == "chroma":
            try:
                kb_vectores.sincronizar(self.db, self.user_id, self.indice, [c["id"] for c in self.chunks])
            except Exception as exc:  # noqa: BLE001
                logger.warning("Chroma no disponible (%s); se usa coseno sobre MySQL", exc)
                self.db.rollback()  # por si falló la query de sincronizar
                self.backend = "mysql"
                return self._cargar()
            return

        # Solo vectores del modelo activo (pueden coexistir otros en BD)
        modelo = active_embedding_model()
        self._embeddings = {
            c.chunk_uid: c.embedding.embedding
            for c in rows
            if c.embedding and c.embedding.embedding and c.embedding.model == modelo
        }
        if self.chunks and not self._embeddings:
            logger.warning(
                "Sin embeddings del modelo '%s' para user=%s indice=%s; "
                "solo BM25. Reprocesa la KB si quieres búsqueda semántica.",
                modelo,
                self.user_id,
                self.indice,
            )

    def close(self) -> None:
        if self._own_session:
            self.db.close()

    def _ranking_semantico_scored(self, consulta: str, n: int) -> list[tuple[str, float]]:
        """Pares (chunk_uid, similitud coseno) ordenados de mayor a menor."""
        if self.backend == "chroma":
            try:
                return kb_vectores.buscar_con_distancia(
                    self.user_id, self.indice, self._embedder.embed_query(consulta), n
                )
            except Exception as exc:  # noqa: BLE001 - queda el ranking BM25
                logger.warning("Chroma: búsqueda semántica fallida (%s); solo BM25", exc)
                return []
        if not self._embeddings:
            return []
        q_vec = np.array(self._embedder.embed_query(consulta), dtype=float)
        sims = sorted(
            ((cid, _cosine(q_vec, np.array(emb, dtype=float))) for cid, emb in self._embeddings.items()),
            key=lambda x: x[1],
            reverse=True,
        )
        return sims[:n]

    def _ranking_semantico(self, consulta: str, n: int) -> list[str]:
        return [cid for cid, _ in self._ranking_semantico_scored(consulta, n)]

    def buscar(self, consulta: str, k: int = 4) -> list[dict]:
        if not self.chunks:
            return []
        rankings = [
            ranking_bm25(self.bm25, [c["id"] for c in self.chunks], consulta, k * 2),
            self._ranking_semantico(consulta, k * 2),
        ]
        por_id = {c["id"]: c for c in self.chunks}
        return [por_id[i] for i in fusion_rrf(rankings, k) if i in por_id]

    def buscar_con_score(self, consulta: str, k: int = 4) -> list[tuple[dict, float]]:
        """Top-k con puntuación de relevancia en [0, 1] (coseno; si no hay, BM25 normalizado)."""
        if not self.chunks:
            return []
        por_id = {c["id"]: c for c in self.chunks}
        sem = self._ranking_semantico_scored(consulta, k * 2)
        sem_score = {cid: score for cid, score in sem}
        ids_bm25 = ranking_bm25(self.bm25, [c["id"] for c in self.chunks], consulta, k * 2)
        # BM25 crudo → [0, 1] relativo al mejor del lote (solo fallback léxico).
        bm25_raw = self.bm25.get_scores(tokenizar(consulta)) if self.bm25 is not None else []
        max_bm25 = float(max(bm25_raw)) if len(bm25_raw) else 0.0
        bm25_score = {
            cid: (float(bm25_raw[i]) / max_bm25 if max_bm25 > 0 else 0.0)
            for i, cid in enumerate([c["id"] for c in self.chunks])
            if cid in ids_bm25 or cid in sem_score
        }
        fusionados = fusion_rrf([ids_bm25, [cid for cid, _ in sem]], k)
        out: list[tuple[dict, float]] = []
        for cid in fusionados:
            chunk = por_id.get(cid)
            if chunk is None:
                continue
            score = max(sem_score.get(cid, 0.0), bm25_score.get(cid, 0.0))
            out.append((chunk, score))
        return out


@lru_cache(maxsize=64)
def obtener_retriever(user_id: int, indice: str) -> RetrieverHibridoMySQL:
    return RetrieverHibridoMySQL(user_id, indice)


def invalidar_cache_retriever(user_id: int | None = None) -> None:
    obtener_retriever.cache_clear()
