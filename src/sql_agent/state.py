"""Estado del grafo LangGraph del SQL Agent."""

from typing import Annotated

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    # Cuenta los pasos del loop query_gen -> correct_query -> execute_query.
    # should_continue() lo usa para cortar con una respuesta controlada al
    # llegar a MAX_SQL_AGENT_ITERACIONES, en vez de dejar que se dispare
    # RECURSION_LIMIT (excepción cruda -> SqlQuery marcada "failed").
    retry_count: int
    # Nº de db_query_tool ejecutadas con éxito (sin "Error:"). should_continue()
    # exige al menos una antes de aceptar SubmitFinalAnswer: sin esto, el LLM
    # puede "responder" con un dato inventado en el primer turno sin haber
    # consultado la BD (visto en producción con gpt-4o-mini pese a la regla
    # explícita del prompt de no inventar datos).
    queries_ok: int
