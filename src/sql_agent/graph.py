"""Grafo LangGraph del SQL Agent.

Topología:

    START -> list_tables_tool -> model_get_schema -> get_schema_tool -> query_gen
    query_gen -> [should_continue]
                   |-> END (SubmitFinalAnswer, con >= 1 consulta ya ejecutada)
                   |-> exigir_consulta -> query_gen (SubmitFinalAnswer sin haber
                   |      consultado la BD: se rechaza, no se acepta un dato inventado)
                   |-> retry_agotado -> END (se superó MAX_SQL_AGENT_ITERACIONES)
                   |-> "query_gen" (self-loop, error de generación)
                   '-> correct_query (ProponerConsultaSQL, o texto plano legado)
                          -> execute_query -> query_gen (loop)

No es un agente ReAct genérico (`create_react_agent`, como los de
`src/agents/`): es un `StateGraph` a medida con su propio loop de
autocorrección SQL, portado de la arquitectura probada en el SQL Agent de
Mercurio (docs/arquitectura.md §6.5).

`retry_agotado` corta el loop de autocorrección con una respuesta controlada
cuando se alcanza MAX_SQL_AGENT_ITERACIONES, en vez de dejar que se dispare
RECURSION_LIMIT como una excepción cruda.

`exigir_consulta` es una salvaguarda estructural (no depende del prompt):
gpt-4o-mini puede invocar SubmitFinalAnswer en el primer turno con un dato
inventado, saltándose la regla "no inventes datos" del prompt. `queries_ok`
en el estado cuenta las db_query_tool exitosas; sin al menos una, no hay
SubmitFinalAnswer válido.
"""

from __future__ import annotations

from typing import Literal

from langchain_community.utilities import SQLDatabase
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from src.config import MAX_SQL_AGENT_ITERACIONES
from src.llm import get_chat_model
from src.sql_agent.database import get_sql_database
from src.sql_agent.prompts import QUERY_CHECK_SYSTEM, QUERY_GEN_SYSTEM
from src.sql_agent.state import State
from src.sql_agent.tools import (
    ProponerConsultaSQL,
    SubmitFinalAnswer,
    build_sql_tools,
    create_tool_node_with_fallback,
)

RECURSION_LIMIT = 2 * MAX_SQL_AGENT_ITERACIONES + 5


def construir_grafo(
    tenant: str,
    agent_db_uri: str | None = None,
    db: SQLDatabase | None = None,
    checkpointer=None,
):
    """Compila el grafo para un tenant concreto (`tenant` = user_id del docente).

    `db` permite inyectar una BD distinta (p. ej. una SQLite de prueba) en
    vez de resolverla desde `(tenant, agent_db_uri)`. `tenant` viaja en el
    closure del grafo (no en el `State` de mensajes).
    """
    db = db or get_sql_database(tenant, agent_db_uri)
    llm = get_chat_model(temperature=0)
    tools = build_sql_tools(db, llm, tenant)

    list_tables_tool = tools["list_tables_tool"]
    schema_tool = tools["get_schema_tool"]
    db_query_tool = tools["db_query_tool"]

    query_gen_llm = llm.bind_tools([SubmitFinalAnswer, ProponerConsultaSQL])
    model_get_schema_llm = llm.bind_tools([schema_tool])

    def primer_llamado(state: State) -> dict:
        return {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "sql_db_list_tables", "args": {}, "id": "tool_first_call"}
                    ],
                )
            ],
            "retry_count": 0,
            "queries_ok": 0,
        }

    def model_get_schema(state: State) -> dict:
        return {"messages": [model_get_schema_llm.invoke(state["messages"])]}

    def query_gen(state: State) -> dict:
        ultimo = state["messages"][-1] if state["messages"] else None
        retry_count = state.get("retry_count", 0)
        queries_ok = state.get("queries_ok", 0)
        contenido = getattr(ultimo, "content", None)
        if isinstance(contenido, str) and contenido.startswith("Error:"):
            retry_count += 1
        elif isinstance(ultimo, ToolMessage) and getattr(ultimo, "name", None) == "db_query_tool":
            queries_ok += 1
        mensaje = query_gen_llm.invoke(
            [{"role": "system", "content": QUERY_GEN_SYSTEM}, *state["messages"]]
        )
        return {"messages": [mensaje], "retry_count": retry_count, "queries_ok": queries_ok}

    def exigir_consulta(state: State) -> dict:
        """Rechaza un SubmitFinalAnswer sin ninguna db_query_tool exitosa previa.

        gpt-4o-mini a veces "responde" en el primer turno con un dato
        inventado, saltándose la regla del prompt de consultar la BD antes de
        contestar. Como el prompt no es una barrera confiable (igual que el
        validador SQL no confía en él), se fuerza aquí: sin evidencia de al
        menos una consulta exitosa, no hay SubmitFinalAnswer válido.
        """
        ultimo = state["messages"][-1]
        mensaje_error = (
            "Error: no has ejecutado ninguna consulta SQL todavía, así que no puedes "
            "responder — el dato que ibas a dar no está verificado contra la base de "
            "datos. NO llames a SubmitFinalAnswer en tu próximo turno. Llama a "
            "ProponerConsultaSQL con la sentencia SQL SELECT que quieres ejecutar "
            "contra las tablas ya listadas para obtener el dato real."
        )
        # Responde a TODAS las tool_calls del turno, no solo la primera: la API
        # de OpenAI puede devolver varias en paralelo (p. ej. SubmitFinalAnswer
        # duplicada) y exige un ToolMessage por cada tool_call_id o rechaza la
        # siguiente llamada completa con 400 "did not have response messages".
        return {
            "messages": [
                ToolMessage(content=mensaje_error, tool_call_id=tc["id"])
                for tc in ultimo.tool_calls
            ],
            "retry_count": state.get("retry_count", 0) + 1,
        }

    def correct_query(state: State) -> dict:
        ultimo = state["messages"][-1]
        tool_calls = getattr(ultimo, "tool_calls", None) or []
        propuesta = next((tc for tc in tool_calls if tc.get("name") == "ProponerConsultaSQL"), None)
        # Compatibilidad: si el modelo aún así devuelve la query como texto
        # plano sin tool_calls, se usa igual (should_continue ya cae aquí).
        ultima_query = propuesta["args"].get("query", "") if propuesta else ultimo.content
        revisada = llm.invoke(
            [
                {"role": "system", "content": QUERY_CHECK_SYSTEM},
                {"role": "user", "content": ultima_query},
            ]
        )
        # `ultimo` puede traer varias tool_calls en paralelo (p. ej. dos
        # ProponerConsultaSQL): TODAS quedan sin responder todavía y hay que
        # cerrarlas antes de encadenar otro AIMessage con tool_calls, o la API
        # de OpenAI rechaza la siguiente llamada con 400 "did not have
        # response messages".
        nuevos_mensajes: list = [
            ToolMessage(
                content="Consulta recibida, revisando antes de ejecutar."
                if tc is propuesta
                else "Ignorada: solo se procesa una propuesta de consulta por turno.",
                tool_call_id=tc["id"],
            )
            for tc in tool_calls
        ]
        nuevos_mensajes.append(
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "db_query_tool",
                        "args": {"query": revisada.content},
                        "id": f"corrected_{len(state['messages'])}",
                    }
                ],
            )
        )
        return {
            "messages": nuevos_mensajes,
            "retry_count": state.get("retry_count", 0) + 1,
        }

    def retry_agotado(state: State) -> dict:
        return {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "SubmitFinalAnswer",
                            "args": {
                                "final_answer": (
                                    "No pude generar una consulta SQL válida tras "
                                    f"{MAX_SQL_AGENT_ITERACIONES} intentos. Reformula la "
                                    "pregunta o revisa que las tablas necesarias existan."
                                )
                            },
                            "id": "tool_retry_agotado",
                        }
                    ],
                )
            ]
        }

    def should_continue(
        state: State,
    ) -> Literal["__end__", "correct_query", "query_gen", "retry_agotado", "exigir_consulta"]:
        if state.get("retry_count", 0) >= MAX_SQL_AGENT_ITERACIONES:
            return "retry_agotado"
        last_message = state["messages"][-1]
        tool_calls = getattr(last_message, "tool_calls", None) or []
        nombres = {tc.get("name") for tc in tool_calls}
        if "SubmitFinalAnswer" in nombres:
            # Solo se acepta si ya hubo al menos una consulta SQL ejecutada.
            if state.get("queries_ok", 0) < 1:
                return "exigir_consulta"
            return END
        if "ProponerConsultaSQL" in nombres:
            return "correct_query"
        if isinstance(last_message.content, str) and last_message.content.startswith("Error:"):
            return "query_gen"
        # Compatibilidad: texto plano sin tool_calls (comportamiento legado).
        return "correct_query"

    grafo = StateGraph(State)
    grafo.add_node("list_tables_tool", create_tool_node_with_fallback([list_tables_tool]))
    grafo.add_node("model_get_schema", model_get_schema)
    grafo.add_node("get_schema_tool", create_tool_node_with_fallback([schema_tool]))
    grafo.add_node("query_gen", query_gen)
    grafo.add_node("correct_query", correct_query)
    grafo.add_node("execute_query", create_tool_node_with_fallback([db_query_tool]))
    grafo.add_node("retry_agotado", retry_agotado)
    grafo.add_node("primer_llamado", primer_llamado)
    grafo.add_node("exigir_consulta", exigir_consulta)

    grafo.add_edge(START, "primer_llamado")
    grafo.add_edge("primer_llamado", "list_tables_tool")
    grafo.add_edge("list_tables_tool", "model_get_schema")
    grafo.add_edge("model_get_schema", "get_schema_tool")
    grafo.add_edge("get_schema_tool", "query_gen")
    grafo.add_conditional_edges(
        "query_gen",
        should_continue,
        {
            END: END,
            "correct_query": "correct_query",
            "query_gen": "query_gen",
            "retry_agotado": "retry_agotado",
            "exigir_consulta": "exigir_consulta",
        },
    )
    grafo.add_edge("correct_query", "execute_query")
    grafo.add_edge("execute_query", "query_gen")
    grafo.add_edge("exigir_consulta", "query_gen")
    grafo.add_edge("retry_agotado", END)

    return grafo.compile(checkpointer=checkpointer or MemorySaver())
