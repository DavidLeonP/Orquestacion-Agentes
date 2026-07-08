"""Fábrica de agentes ReAct (directriz de orquestación §2.2).

Cada agente es un subgrafo ReAct de LangGraph: razona, llama tools RAG,
observa la evidencia e itera hasta MAX_ITERACIONES_REACT.
"""

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from src.config import LLM_MODEL, MAX_ITERACIONES_REACT

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
    llm = ChatOpenAI(model=LLM_MODEL, temperature=0)
    return create_react_agent(
        llm,
        tools,
        prompt=f"{prompt}\n\n{DIRECTRIZ_GROUNDING}",
        name=nombre,
    )


def ejecutar_agente(agente, peticion: str) -> str:
    """Ejecuta el bucle ReAct con límite de iteraciones y devuelve la respuesta final."""
    resultado = agente.invoke(
        {"messages": [HumanMessage(content=peticion)]},
        # Cada iteración ReAct son 2 pasos (modelo + tools) + margen.
        config={"recursion_limit": 2 * MAX_ITERACIONES_REACT + 5},
    )
    return resultado["messages"][-1].content
