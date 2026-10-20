"""Cliente ChromaDB compartido (embebido, PersistentClient en storage/chroma).

ChromaDB falla con KeyError si varios PersistentClient se abren en paralelo sobre
el mismo path (p. ej. cuando el Exam Generator llama varias tools RAG a la vez).
Un único cliente + lock evita esa condición de carrera.

Colecciones con vectores propios (los calcula el model registry, no Chroma):
- `kb_<modelo>`: chunks de la KB de todos los usuarios, filtrados por `user_id`.
- `casos_<modelo>`: exámenes aprobados por el docente (memoria de casos).
Una colección por modelo de embeddings evita mezclar dimensiones al cambiar de perfil.
"""

import re
import threading

import chromadb

from src.config import DIR_CHROMA
from src.llm import active_embedding_model

_lock = threading.RLock()
_client = None


def obtener_cliente_chroma():
    global _client
    with _lock:
        if _client is None:
            _client = chromadb.PersistentClient(path=str(DIR_CHROMA))
        return _client


def coleccion_vectores(prefijo: str):
    """Colección cruda `<prefijo>_<modelo activo>` con distancia coseno."""
    # Chroma 1.x: [A-Za-z0-9_.-], empezar y terminar en alfanumérico
    nombre = f"{prefijo}_{re.sub(r'[^A-Za-z0-9_-]', '_', active_embedding_model())}".strip("_-.")
    with _lock:
        return obtener_cliente_chroma().get_or_create_collection(
            nombre, metadata={"hnsw:space": "cosine"}
        )


def filtro(**campos) -> dict:
    """Filtro `where` de Chroma para uno o varios campos exactos."""
    condiciones = [{k: v} for k, v in campos.items()]
    return condiciones[0] if len(condiciones) == 1 else {"$and": condiciones}


def id_vector(user_id: int, chunk_uid: str) -> str:
    # chunk_uid solo es único por usuario (uq_user_chunk_uid)
    return f"{user_id}:{chunk_uid}"
