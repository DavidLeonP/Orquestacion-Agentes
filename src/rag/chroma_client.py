"""Cliente ChromaDB compartido.

ChromaDB falla con KeyError si varios PersistentClient se abren en paralelo sobre
el mismo path (p. ej. cuando el Exam Generator llama varias tools RAG a la vez).
Un único cliente + lock evita esa condición de carrera.
"""

import threading
from functools import lru_cache

import chromadb
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings

from src.config import DIR_CHROMA, EMBEDDING_MODEL

_lock = threading.RLock()
_client = None
_colecciones: dict[str, Chroma] = {}


def obtener_cliente_chroma():
    global _client
    with _lock:
        if _client is None:
            _client = chromadb.PersistentClient(path=str(DIR_CHROMA))
        return _client


@lru_cache(maxsize=1)
def obtener_embeddings() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(model=EMBEDDING_MODEL)


def obtener_coleccion(indice: str) -> Chroma:
    with _lock:
        if indice not in _colecciones:
            _colecciones[indice] = Chroma(
                client=obtener_cliente_chroma(),
                collection_name=indice,
                embedding_function=obtener_embeddings(),
            )
        return _colecciones[indice]
