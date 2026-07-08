"""Retriever híbrido: BM25 (léxico) + ChromaDB (semántico) fusionados con RRF.

Directriz de conocimiento (docs/arquitectura.md §3.3): la búsqueda léxica captura
terminología exacta ("ley de Ohm") y la semántica es robusta a paráfrasis; la
fusión Reciprocal Rank Fusion combina ambos rankings sin calibrar puntuaciones.
"""

import json
import re
from functools import lru_cache

from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
from rank_bm25 import BM25Okapi

from src.config import DIR_CHROMA, DIR_STORAGE, EMBEDDING_MODEL

DIR_CHUNKS = DIR_STORAGE / "chunks"
RRF_K = 60


def _tokenizar(texto: str) -> list[str]:
    return re.findall(r"\w+", texto.lower())


class RetrieverHibrido:
    def __init__(self, indice: str):
        self.indice = indice
        ruta = DIR_CHUNKS / f"{indice}.json"
        if not ruta.exists():
            raise FileNotFoundError(
                f"No existe el índice '{indice}'. Ejecuta primero: python main.py ingestar"
            )
        self.chunks: list[dict] = json.loads(ruta.read_text(encoding="utf-8"))
        self.bm25 = BM25Okapi([_tokenizar(c["texto"]) for c in self.chunks])
        self.chroma = Chroma(
            collection_name=indice,
            embedding_function=OpenAIEmbeddings(model=EMBEDDING_MODEL),
            persist_directory=str(DIR_CHROMA),
        )

    def buscar(self, consulta: str, k: int = 4) -> list[dict]:
        """Devuelve los k mejores chunks según fusión RRF de BM25 y semántica."""
        puntuaciones: dict[str, float] = {}

        # Ranking léxico
        scores_bm25 = self.bm25.get_scores(_tokenizar(consulta))
        ranking_lexico = sorted(
            range(len(self.chunks)), key=lambda i: scores_bm25[i], reverse=True
        )[: k * 2]
        for pos, idx in enumerate(ranking_lexico):
            chunk_id = self.chunks[idx]["id"]
            puntuaciones[chunk_id] = puntuaciones.get(chunk_id, 0) + 1 / (RRF_K + pos + 1)

        # Ranking semántico
        for pos, doc in enumerate(self.chroma.similarity_search(consulta, k=k * 2)):
            chunk_id = next(
                (c["id"] for c in self.chunks if c["texto"] == doc.page_content), None
            )
            if chunk_id:
                puntuaciones[chunk_id] = puntuaciones.get(chunk_id, 0) + 1 / (RRF_K + pos + 1)

        mejores_ids = sorted(puntuaciones, key=puntuaciones.get, reverse=True)[:k]
        por_id = {c["id"]: c for c in self.chunks}
        return [por_id[i] for i in mejores_ids]


@lru_cache(maxsize=8)
def obtener_retriever(indice: str) -> RetrieverHibrido:
    return RetrieverHibrido(indice)
