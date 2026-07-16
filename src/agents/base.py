"""Fábrica de agentes ReAct (directriz de orquestación §2.2).

Cada agente es un subgrafo ReAct de LangGraph: razona, llama tools RAG,
observa la evidencia e itera hasta MAX_ITERACIONES_REACT.
"""

import time
from typing import TypeVar

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.prebuilt import create_react_agent
from pydantic import BaseModel

from src.agents.schemas import safe_parse
from src.config import MAX_ITERACIONES_REACT
from src.llm import get_chat_model
from src.observability.trazas import registrar_evento

T = TypeVar("T", bound=BaseModel)

DIRECTRIZ_GROUNDING = (
    "REGLAS DE GROUNDING (obligatorias):\n"
    "1. NO respondas 'en general': apóyate SIEMPRE en la base documental del "
    "instituto usando tus herramientas de búsqueda antes de generar contenido.\n"
    "2. Cita las fuentes consultadas al final de tu respuesta en una sección "
    "'Fuentes consultadas', usando el nombre de archivo que aparece en "
    "[fuente: ...].\n"
    "3. Si la base documental no contiene evidencia suficiente, decláralo "
    "explícitamente en lugar de inventar.\n"
    "4. Responde siempre en español."
)


def crear_agente(nombre: str, prompt: str, tools: list):
    llm = get_chat_model(temperature=0)
    return create_react_agent(
        llm,
        tools,
        prompt=f"{prompt}\n\n{DIRECTRIZ_GROUNDING}",
        name=nombre,
    )


def ejecutar_agente(agente, peticion: str, nombre: str = "agente") -> str:
    """Ejecuta el bucle ReAct con límite de iteraciones y devuelve la respuesta final."""
    registrar_evento("agente_inicio", agente=nombre, peticion=peticion[:300])
    inicio = time.perf_counter()

    resultado = agente.invoke(
        {"messages": [HumanMessage(content=peticion)]},
        config={"recursion_limit": 2 * MAX_ITERACIONES_REACT + 5},
    )

    tools_usadas = []
    for m in resultado["messages"]:
        if isinstance(m, AIMessage) and m.tool_calls:
            tools_usadas.extend(tc["name"] for tc in m.tool_calls)
        elif isinstance(m, ToolMessage) and getattr(m, "name", None):
            tools_usadas.append(m.name)
    iteraciones = sum(1 for m in resultado["messages"] if isinstance(m, AIMessage))
    respuesta = resultado["messages"][-1].content
    if not isinstance(respuesta, str):
        respuesta = str(respuesta)

    registrar_evento(
        "agente_fin",
        agente=nombre,
        duracion_ms=round((time.perf_counter() - inicio) * 1000),
        iteraciones_llm=iteraciones,
        tools_usadas=tools_usadas,
        longitud_respuesta=len(respuesta),
        cita_fuentes="fuentes consultadas" in respuesta.lower(),
    )
    return respuesta


def estructurar_salida(
    esquema: type[T],
    texto: str,
    *,
    instruccion: str,
    nombre: str = "estructurar",
) -> tuple[T, bool]:
    """Materializa un contrato Pydantic a partir del texto libre del agente.

    Usa structured output del LLM; si falla, `safe_parse` aplica fallback.
    Así se puede cambiar el modelo sin corromper el routing del orquestador.
    """
    registrar_evento("estructurar_inicio", esquema=esquema.__name__, agente=nombre)
    try:
        llm = get_chat_model(temperature=0).with_structured_output(esquema)
        resultado = llm.invoke(
            f"{instruccion}\n\n---\nContenido a estructurar:\n{texto}"
        )
        if isinstance(resultado, esquema):
            modelo, ok = resultado, True
        else:
            modelo, ok = safe_parse(esquema, resultado)
        registrar_evento(
            "estructurar_fin",
            esquema=esquema.__name__,
            ok=ok,
            agente=nombre,
        )
        return modelo, ok
    except Exception as exc:  # noqa: BLE001
        registrar_evento(
            "estructurar_error",
            esquema=esquema.__name__,
            error=str(exc)[:300],
            agente=nombre,
        )
        return safe_parse(esquema, texto)
