"""Tools del SQL Agent: listar tablas, obtener schema, ejecutar query.

Basado en el patrón de "Building a Powerful SQL Agent with LangGraph" (Part 2):
cada tool corre dentro de un ToolNode con fallback, de forma que un error de
tool (SQL mal formado, tabla inexistente, etc.) se devuelve como un
ToolMessage de error en vez de romper el grafo — el propio agente lo lee en
el siguiente paso de query_gen y reintenta.

Las tools se construyen atadas a una instancia concreta de `SQLDatabase` (en
vez de un singleton global) para poder inyectar una BD de prueba en tests
sin tocar la BD de negocio real (AGENT_DB_URI).
"""

from __future__ import annotations

from typing import Any

from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain_community.utilities import SQLDatabase
from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableLambda, RunnableWithFallbacks
from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, Field

from src.sql_agent.executor import ejecutar_sql_validado


class SubmitFinalAnswer(BaseModel):
    """Envía la respuesta final en lenguaje natural al usuario."""

    final_answer: str = Field(..., description="La respuesta final para el usuario")


class ProponerConsultaSQL(BaseModel):
    """Propone la siguiente consulta SQL SELECT a revisar y ejecutar contra la BD.

    Se ofrece como tool explícita (en vez de esperar que el modelo devuelva
    texto plano sin tool_calls) porque modelos pequeños como gpt-4o-mini
    tienden a preferir la única tool que sí conocen (`SubmitFinalAnswer`)
    antes que "no llamar a nada" cuando ambas opciones son válidas — dejarles
    una tool explícita para el otro camino elimina esa ambigüedad.
    """

    query: str = Field(..., description="La sentencia SQL SELECT a ejecutar.")


def handle_tool_error(state: dict) -> dict:
    error = state.get("error")
    tool_calls = state["messages"][-1].tool_calls
    return {
        "messages": [
            ToolMessage(
                content=f"Error: {repr(error)}\n please fix your mistakes.",
                tool_call_id=tc["id"],
            )
            for tc in tool_calls
        ]
    }


def create_tool_node_with_fallback(tools: list) -> RunnableWithFallbacks:
    return ToolNode(tools).with_fallbacks(
        [RunnableLambda(handle_tool_error)], exception_key="error"
    )


def build_sql_tools(db: SQLDatabase, llm: Any, tenant: str) -> dict[str, Any]:
    """Construye list_tables_tool, get_schema_tool y db_query_tool atadas a `db`.

    `tenant` identifica al dueño de `db` y viaja hasta el ejecutor aislado,
    que revalida la consulta de forma independiente antes de tocar la BD —
    no confía en que este wrapper ya validó.
    """
    toolkit = SQLDatabaseToolkit(db=db, llm=llm)
    tools = toolkit.get_tools()
    list_tables_tool = next(t for t in tools if t.name == "sql_db_list_tables")
    schema_tool = next(t for t in tools if t.name == "sql_db_schema")

    @tool
    def db_query_tool(query: str) -> str:
        """Ejecuta una consulta SQL de solo lectura contra la base de datos y
        devuelve el resultado. Si la consulta es incorrecta, devuelve un
        mensaje de error para que se corrija y se reintente."""
        return ejecutar_sql_validado(tenant, db, query)

    return {
        "list_tables_tool": list_tables_tool,
        "get_schema_tool": schema_tool,
        "db_query_tool": db_query_tool,
    }
