"""Fábrica de agentes ReAct (directriz de orquestación §3.2).

Cada agente es un subgrafo ReAct (`langchain.agents.create_agent`): razona,
llama tools RAG, observa la evidencia e itera hasta MAX_ITERACIONES_REACT.
"""

import time
from typing import TypeVar

from langchain.agents import create_agent
from langchain.agents.middleware import wrap_tool_call
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.errors import GraphBubbleUp, GraphRecursionError
from pydantic import BaseModel

from src.agents.schemas import safe_parse
from src.config import MAX_ITERACIONES_REACT
from src.llm import get_chat_model, get_structured_model
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


@wrap_tool_call
def error_como_observacion(request, handler):
    """Un fallo de la tool (p. ej. MySQL caído) vuelve al agente como observación
    en vez de abortar la solicitud; el agente puede reintentar o declarar que no
    hay evidencia (notebook §5C: invocar_herramienta)."""
    try:
        return handler(request)
    except GraphBubbleUp:  # interrupt() y demás control de flujo de LangGraph
        raise
    except Exception as exc:  # noqa: BLE001
        nombre = request.tool_call["name"]
        registrar_evento("tool_error", tool=nombre, error=str(exc)[:300])
        return ToolMessage(
            content=f"Error al ejecutar {nombre}: {type(exc).__name__}. "
            "Reintenta con otra consulta o indica que no consta evidencia.",
            tool_call_id=request.tool_call["id"],
            name=nombre,
            status="error",
        )


def crear_agente(nombre: str, prompt: str, tools: list, model: str | None = None):
    return create_agent(
        get_chat_model(temperature=0, model=model),
        tools,
        system_prompt=f"{prompt}\n\n{DIRECTRIZ_GROUNDING}",
        middleware=[error_como_observacion],
        name=nombre,
    )


def ejecutar_agente(agente, peticion: str, nombre: str = "agente") -> str:
    """Ejecuta el bucle ReAct con límite de iteraciones y devuelve la respuesta final.

    Si se agotan las iteraciones devuelve una respuesta controlada (como el
    "se alcanzó MAX_STEPS" del notebook) en vez de propagar GraphRecursionError.
    """
    registrar_evento("agente_inicio", agente=nombre, peticion=peticion[:300])
    inicio = time.perf_counter()

    try:
        resultado = agente.invoke(
            {"messages": [HumanMessage(content=peticion)]},
            # 2 super-steps (model + tools) por iteración + respuesta final y arranque
            # de create_agent: +3 permite exactamente MAX iteraciones (tests/test_agentes_base.py)
            config={"recursion_limit": 2 * MAX_ITERACIONES_REACT + 3},
        )
    except GraphRecursionError:
        registrar_evento(
            "agente_fin",
            agente=nombre,
            duracion_ms=round((time.perf_counter() - inicio) * 1000),
            limite_iteraciones=True,
        )
        return (
            f"No pude completar la tarea en {MAX_ITERACIONES_REACT} iteraciones. "
            "No consta evidencia suficiente en la base documental."
        )

    tools_usadas = []
    for m in resultado["messages"]:
        if isinstance(m, AIMessage) and m.tool_calls:
            tools_usadas.extend(tc["name"] for tc in m.tool_calls)
        elif isinstance(m, ToolMessage) and getattr(m, "name", None):
            tools_usadas.append(m.name)
    ai = [m for m in resultado["messages"] if isinstance(m, AIMessage)]
    uso = [m.usage_metadata or {} for m in ai]
    respuesta = resultado["messages"][-1].content
    if not isinstance(respuesta, str):
        respuesta = str(respuesta)

    registrar_evento(
        "agente_fin",
        agente=nombre,
        duracion_ms=round((time.perf_counter() - inicio) * 1000),
        iteraciones_llm=len(ai),
        tokens_in=sum(u.get("input_tokens", 0) for u in uso),
        tokens_out=sum(u.get("output_tokens", 0) for u in uso),
        tools_usadas=tools_usadas,
        longitud_respuesta=len(respuesta),
        cita_fuentes="fuentes consultadas" in respuesta.lower(),
    )
    return respuesta


def invocar_estructurado(schema: type[T], prompt: str, model: str | None, fallback: T) -> T:
    """Salida tipada del LLM; ante error de red o de validación, `fallback`."""
    try:
        salida = get_structured_model(schema, temperature=0, model=model).invoke(prompt)
    except Exception:  # noqa: BLE001 - quien llama decide qué significa el fallback
        return fallback
    return safe_parse(schema, salida, fallback=fallback)[0]


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
        llm = get_structured_model(esquema, temperature=0)
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
