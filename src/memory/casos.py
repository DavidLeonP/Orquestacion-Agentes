"""Memoria de casos: exámenes aprobados por el docente (notebook §5C.3).

Colección Chroma `casos_<modelo>`, filtrada por `user_id`. El Exam Generator
recibe los casos parecidos como pistas de estilo, nunca como respuesta. Solo se
escribe tras la aprobación HITL, así que todo caso tiene el visto bueno humano.
"""

from __future__ import annotations

import logging
import uuid

from src.config import UMBRAL_MEMORIA_CASOS
from src.llm import get_embeddings
from src.rag.chroma_client import coleccion_vectores, filtro

logger = logging.getLogger("orquestacion.memoria")

MAX_CHARS_CASO = 1500


def archivar(user_id: int, peticion: str, contenido: str) -> None:
    try:
        coleccion_vectores("casos").add(
            ids=[uuid.uuid4().hex],
            embeddings=[get_embeddings().embed_query(peticion)],
            documents=[contenido[:MAX_CHARS_CASO]],
            metadatas=[{"user_id": user_id, "peticion": peticion[:500]}],
        )
    except Exception as exc:  # noqa: BLE001 - la aprobación no depende de la memoria
        logger.warning("Memoria de casos: no se pudo archivar: %s", exc)


def recordar(user_id: int, peticion: str, k: int = 2) -> list[str]:
    """Hasta k casos con similitud coseno >= UMBRAL_MEMORIA_CASOS."""
    try:
        res = coleccion_vectores("casos").query(
            query_embeddings=[get_embeddings().embed_query(peticion)],
            n_results=k,
            where=filtro(user_id=user_id),
            include=["documents", "metadatas", "distances"],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Memoria de casos: no se pudo consultar: %s", exc)
        return []
    return [
        f"Petición: {m['peticion']}\n{doc}"
        for doc, m, d in zip(res["documents"][0], res["metadatas"][0], res["distances"][0])
        if 1 - d >= UMBRAL_MEMORIA_CASOS
    ]
