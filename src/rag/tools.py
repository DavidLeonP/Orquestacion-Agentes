"""Tools RAG scoped por user_id del contexto."""

import time

from langchain_core.tools import tool

from src.observability.trazas import registrar_evento
from src.rag.context import get_rag_user_id
from src.rag.mysql_store import obtener_retriever


def _formatear(chunks: list[dict]) -> str:
    if not chunks:
        return "Sin resultados en la base documental del usuario."
    bloques = []
    for c in chunks:
        m = c["metadatos"]
        cabecera = (
            f"[fuente: {m.get('fuente')} | {m.get('asignatura', '?')} "
            f"{m.get('curso', '')} {m.get('anio', '')}]"
        )
        bloques.append(f"{cabecera}\n{c['texto']}")
    return "\n\n---\n\n".join(bloques)


def _buscar(indice: str, consulta: str) -> str:
    inicio = time.perf_counter()
    user_id = get_rag_user_id()
    chunks = obtener_retriever(user_id, indice).buscar(consulta)
    registrar_evento(
        "rag_busqueda",
        indice=indice,
        consulta=consulta,
        user_id=user_id,
        num_resultados=len(chunks),
        fuentes=[c["metadatos"].get("fuente") for c in chunks],
        duracion_ms=round((time.perf_counter() - inicio) * 1000),
    )
    return _formatear(chunks)


@tool
def buscar_apuntes(consulta: str) -> str:
    """Busca en los apuntes y material de clase del usuario. Úsala para
    fundamentar explicaciones, definiciones y ejemplos con el material real
    que se imparte en el aula."""
    return _buscar("apuntes", consulta)


@tool
def buscar_examenes_historicos(consulta: str) -> str:
    """Busca en los exámenes de años anteriores del usuario. Úsala para
    conocer el estilo, formato, tipos de pregunta y nivel de dificultad,
    y para evitar repetir preguntas ya usadas."""
    return _buscar("examenes", consulta)


@tool
def buscar_rubricas(consulta: str) -> str:
    """Busca en las rúbricas y criterios de evaluación del usuario.
    Úsala para conocer los criterios de diseño y corrección que debe cumplir
    cualquier material de evaluación."""
    return _buscar("rubricas", consulta)


@tool
def buscar_curriculo(consulta: str) -> str:
    """Busca en el currículo oficial y las programaciones didácticas del
    usuario. Úsala para alinear contenidos, objetivos y criterios de evaluación
    con la programación vigente."""
    return _buscar("curriculo", consulta)
