"""Tools RAG expuestas a los agentes.

Diseñadas como funciones puras y autodescriptivas, listas para exponerse vía un
servidor MCP en el futuro (directriz de orquestación §2.4). Cada resultado
incluye la fuente para garantizar la trazabilidad de las respuestas.
"""

import time

from langchain_core.tools import tool

from src.observability.trazas import registrar_evento
from src.rag.hybrid import obtener_retriever


def _formatear(chunks: list[dict]) -> str:
    if not chunks:
        return "Sin resultados en la base documental del instituto."
    bloques = []
    for c in chunks:
        m = c["metadatos"]
        cabecera = f"[fuente: {m.get('fuente')} | {m.get('asignatura', '?')} {m.get('curso', '')} {m.get('anio', '')}]"
        bloques.append(f"{cabecera}\n{c['texto']}")
    return "\n\n---\n\n".join(bloques)


def _buscar(indice: str, consulta: str) -> str:
    inicio = time.perf_counter()
    chunks = obtener_retriever(indice).buscar(consulta)
    registrar_evento(
        "rag_busqueda",
        indice=indice,
        consulta=consulta,
        num_resultados=len(chunks),
        fuentes=[c["metadatos"].get("fuente") for c in chunks],
        duracion_ms=round((time.perf_counter() - inicio) * 1000),
    )
    return _formatear(chunks)


@tool
def buscar_apuntes(consulta: str) -> str:
    """Busca en los apuntes y material de clase del instituto. Úsala para
    fundamentar explicaciones, definiciones y ejemplos con el material real
    que se imparte en el aula."""
    return _buscar("apuntes", consulta)


@tool
def buscar_examenes_historicos(consulta: str) -> str:
    """Busca en los exámenes de años anteriores del instituto. Úsala para
    conocer el estilo, formato, tipos de pregunta y nivel de dificultad del
    centro, y para evitar repetir preguntas ya usadas."""
    return _buscar("examenes", consulta)


@tool
def buscar_rubricas(consulta: str) -> str:
    """Busca en las rúbricas y criterios de evaluación del departamento.
    Úsala para conocer los criterios de diseño y corrección que debe cumplir
    cualquier material de evaluación."""
    return _buscar("rubricas", consulta)


@tool
def buscar_curriculo(consulta: str) -> str:
    """Busca en el currículo oficial y las programaciones didácticas del
    centro. Úsala para alinear contenidos, objetivos y criterios de evaluación
    con la programación vigente."""
    return _buscar("curriculo", consulta)
