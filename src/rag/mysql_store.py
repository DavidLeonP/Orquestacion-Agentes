"""Retriever híbrido sobre MySQL: BM25 + embeddings + RRF."""

from __future__ import annotations

import re
from functools import lru_cache

import numpy as np
from langchain_openai import OpenAIEmbeddings
from rank_bm25 import BM25Okapi
from sqlalchemy.orm import Session, joinedload

from src.config import EMBEDDING_MODEL
from src.db.models import Chunk
from src.db.session import SessionLocal

RRF_K = 60


def _tokenizar(texto: str) -> list[str]:
    return re.findall(r"\w+", texto.lower())


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
        self.chunks: list[dict] = []
        self._embeddings: dict[str, list[float]] = {}
        self._cargar()

    def _cargar(self) -> None:
        rows = (
            self.db.query(Chunk)
            .options(joinedload(Chunk.embedding))
            .filter(Chunk.user_id == self.user_id, Chunk.indice == self.indice)
            .order_by(Chunk.position)
            .all()
        )
        self.chunks = []
        self._embeddings = {}
        for c in rows:
            item = {
                "id": c.chunk_uid,
                "texto": c.texto,
                "metadatos": c.metadatos or {},
            }
            self.chunks.append(item)
            if c.embedding and c.embedding.embedding:
                self._embeddings[c.chunk_uid] = c.embedding.embedding
        self.bm25 = (
            BM25Okapi([_tokenizar(c["texto"]) for c in self.chunks]) if self.chunks else None
        )
        self._embedder = OpenAIEmbeddings(model=EMBEDDING_MODEL)

    def close(self) -> None:
        if self._own_session:
            self.db.close()

    def buscar(self, consulta: str, k: int = 4) -> list[dict]:
        if not self.chunks:
            return []

        puntuaciones: dict[str, float] = {}

        if self.bm25 is not None:
            scores = self.bm25.get_scores(_tokenizar(consulta))
            ranking = sorted(range(len(self.chunks)), key=lambda i: scores[i], reverse=True)[
                : k * 2
            ]
            for pos, idx in enumerate(ranking):
                cid = self.chunks[idx]["id"]
                puntuaciones[cid] = puntuaciones.get(cid, 0) + 1 / (RRF_K + pos + 1)

        if self._embeddings:
            q_vec = np.array(self._embedder.embed_query(consulta), dtype=float)
            sims = []
            for c in self.chunks:
                emb = self._embeddings.get(c["id"])
                if emb is None:
                    continue
                sims.append((c["id"], _cosine(q_vec, np.array(emb, dtype=float))))
            sims.sort(key=lambda x: x[1], reverse=True)
            for pos, (cid, _) in enumerate(sims[: k * 2]):
                puntuaciones[cid] = puntuaciones.get(cid, 0) + 1 / (RRF_K + pos + 1)

        mejores = sorted(puntuaciones, key=puntuaciones.get, reverse=True)[:k]
        por_id = {c["id"]: c for c in self.chunks}
        return [por_id[i] for i in mejores if i in por_id]


@lru_cache(maxsize=64)
def obtener_retriever(user_id: int, indice: str) -> RetrieverHibridoMySQL:
    return RetrieverHibridoMySQL(user_id, indice)


def invalidar_cache_retriever(user_id: int | None = None) -> None:
    if user_id is None:
        obtener_retriever.cache_clear()
        return
    # lru_cache no permite borrar por clave parcial; limpiamos todo
    obtener_retriever.cache_clear()
