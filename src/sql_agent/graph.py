"""Grafo LangGraph del SQL Agent.

Topología:

    START -> primer_llamado -> list_tables_tool -> model_get_schema
          -> get_schema_tool -> cargar_memoria -> query_gen
    query_gen -> [should_continue]
                   |-> validar_respuesta (SubmitFinalAnswer + queries_ok >= 1)
                   |      -> [tras_validar]
                   |           |-> emitir_respuesta -> END
                   |           |-> aclaracion_humana (interrupt HITL) -> query_gen
                   |           |-> reflexionar -> query_gen
                   |-> exigir_consulta -> query_gen
                   |-> retry_agotado -> END
                   |-> query_gen (error de generación)
                   '-> correct_query -> execute_query -> query_gen

Reflexion (como en exámenes): validación determinista (+ LLM opcional),
lecciones en estado, y aclaraciones persistidas en Chroma
(`src/memory/clarificaciones_sql.py`).
"""

from __future__ import annotations

from typing import Literal

from langchain_community.utilities import SQLDatabase
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from src.agents.base import invocar_estructurado
from src.agents.schemas import Reflexion, dump_state
from src.config import EVAL_MODEL, MAX_SQL_AGENT_ITERACIONES
from src.llm import get_chat_model
from src.memory import clarificaciones_sql as memoria_sql
from src.sql_agent.database import get_sql_database
from src.sql_agent.knowledge_graph import system_prompt_query_gen
from src.sql_agent.prompts import QUERY_CHECK_SYSTEM, QUERY_GEN_SYSTEM
from src.sql_agent.reflexion import (
    bloque_memoria,
    extraer_peticion,
    extraer_submit,
    extraer_ultimo_sql,
    leccion,
    prompt_reflexion_sql,
    prompt_veredicto_llm,
    siguiente_paso_sql,
    verificar_respuesta,
)
from src.sql_agent.schemas import PayloadAclaracionSql, VeredictoSql
from src.sql_agent.state import State
from src.sql_agent.tools import (
    ProponerConsultaSQL,
    SubmitFinalAnswer,
    build_sql_tools,
    create_tool_node_with_fallback,
)

RECURSION_LIMIT = 2 * MAX_SQL_AGENT_ITERACIONES + 15


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
    query_system_base = system_prompt_query_gen(QUERY_GEN_SYSTEM)

    list_tables_tool = tools["list_tables_tool"]
    schema_tool = tools["get_schema_tool"]
    db_query_tool = tools["db_query_tool"]

    query_gen_llm = llm.bind_tools([SubmitFinalAnswer, ProponerConsultaSQL])
    model_get_schema_llm = llm.bind_tools([schema_tool])

    def primer_llamado(state: State) -> dict:
        peticion = state.get("peticion") or extraer_peticion(state.get("messages") or [])
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
            "peticion": peticion,
            "lecciones": list(state.get("lecciones") or []),
            "clarificaciones": list(state.get("clarificaciones") or []),
            "intentos_validacion": int(state.get("intentos_validacion") or 0),
        }

    def model_get_schema(state: State) -> dict:
        return {"messages": [model_get_schema_llm.invoke(state["messages"])]}

    def cargar_memoria(state: State) -> dict:
        """Recupera aclaraciones Chroma parecidas a la petición."""
        peticion = state.get("peticion") or extraer_peticion(state.get("messages") or [])
        recordadas = memoria_sql.recordar(tenant, peticion)
        previas = list(state.get("clarificaciones") or [])
        # Deduplicar manteniendo orden
        vistas = set(previas)
        merged = list(previas)
        for c in recordadas:
            if c not in vistas:
                merged.append(c)
                vistas.add(c)
        return {"peticion": peticion, "clarificaciones": merged}

    def query_gen(state: State) -> dict:
        ultimo = state["messages"][-1] if state["messages"] else None
        retry_count = state.get("retry_count", 0)
        queries_ok = state.get("queries_ok", 0)
        contenido = getattr(ultimo, "content", None)
        if isinstance(contenido, str) and contenido.startswith("Error:"):
            retry_count += 1
        elif isinstance(ultimo, ToolMessage) and getattr(ultimo, "name", None) == "db_query_tool":
            queries_ok += 1
        sistema = query_system_base + bloque_memoria(
            list(state.get("clarificaciones") or []),
            list(state.get("lecciones") or []),
        )
        mensaje = query_gen_llm.invoke(
            [{"role": "system", "content": sistema}, *state["messages"]]
        )
        return {"messages": [mensaje], "retry_count": retry_count, "queries_ok": queries_ok}

    def exigir_consulta(state: State) -> dict:
        ultimo = state["messages"][-1]
        mensaje_error = (
            "Error: no has ejecutado ninguna consulta SQL todavía, así que no puedes "
            "responder — el dato que ibas a dar no está verificado contra la base de "
            "datos. NO llames a SubmitFinalAnswer en tu próximo turno. Llama a "
            "ProponerConsultaSQL con la sentencia SQL SELECT que quieres ejecutar "
            "contra las tablas ya listadas para obtener el dato real."
        )
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
        ultima_query = propuesta["args"].get("query", "") if propuesta else ultimo.content
        revisada = llm.invoke(
            [
                {"role": "system", "content": QUERY_CHECK_SYSTEM},
                {"role": "user", "content": ultima_query},
            ]
        )
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

    def validar_respuesta(state: State) -> dict:
        """Cierra SubmitFinalAnswer y evalúa coherencia (determinista + LLM)."""
        ultimo = state["messages"][-1]
        tool_calls = getattr(ultimo, "tool_calls", None) or []
        respuesta, _ = extraer_submit([ultimo])
        sql = extraer_ultimo_sql(state["messages"])
        peticion = state.get("peticion") or extraer_peticion(state["messages"])
        clarificaciones = list(state.get("clarificaciones") or [])

        veredicto = verificar_respuesta(
            peticion, respuesta, sql, clarificaciones=clarificaciones
        )
        # Si el determinista aprueba, un pase LLM puede pedir aclaración o rechazar.
        if veredicto.aprobado:
            veredicto = invocar_estructurado(
                VeredictoSql,
                prompt_veredicto_llm(peticion, respuesta, sql, veredicto.motivos),
                EVAL_MODEL,
                fallback=veredicto,
            )
        elif not veredicto.necesita_aclaracion:
            # Refuerzo LLM opcional sobre el rechazo determinista
            llm_v = invocar_estructurado(
                VeredictoSql,
                prompt_veredicto_llm(peticion, respuesta, sql, veredicto.motivos),
                EVAL_MODEL,
                fallback=veredicto,
            )
            # Conservar motivos deterministas; permitir que el LLM marque aclaración
            if llm_v.necesita_aclaracion:
                veredicto.necesita_aclaracion = True
                veredicto.pregunta_aclaracion = (
                    llm_v.pregunta_aclaracion or veredicto.pregunta_aclaracion
                )

        intentos = int(state.get("intentos_validacion") or 0) + 1
        cierre = [
            ToolMessage(
                content=(
                    "Respuesta aceptada por validación."
                    if veredicto.aprobado
                    else "Respuesta rechazada por validación: "
                    + "; ".join(veredicto.motivos or [veredicto.resumen])
                ),
                tool_call_id=tc["id"],
            )
            for tc in tool_calls
        ]
        return {
            "messages": cierre,
            "veredicto": dump_state(veredicto),
            "borrador_final": respuesta,
            "sql_final": sql,
            "intentos_validacion": intentos,
            "peticion": peticion,
        }

    def tras_validar(
        state: State,
    ) -> Literal["emitir_respuesta", "aclaracion_humana", "reflexionar"]:
        raw = state.get("veredicto") or {}
        veredicto = VeredictoSql.model_validate(raw) if raw else VeredictoSql(
            aprobado=False, motivos=["sin veredicto"]
        )
        return siguiente_paso_sql(veredicto, int(state.get("intentos_validacion") or 0))  # type: ignore[return-value]

    def emitir_respuesta(state: State) -> dict:
        texto = state.get("borrador_final") or (
            "No hay una respuesta validada disponible."
        )
        return {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "SubmitFinalAnswer",
                            "args": {"final_answer": texto},
                            "id": "tool_emitir_validado",
                        }
                    ],
                )
            ]
        }

    def reflexionar(state: State) -> dict:
        raw = state.get("veredicto") or {}
        veredicto = VeredictoSql.model_validate(raw) if raw else VeredictoSql(
            aprobado=False, motivos=["rechazo"]
        )
        previas = list(state.get("lecciones") or [])
        n = int(state.get("intentos_validacion") or 1)
        r = invocar_estructurado(
            Reflexion,
            prompt_reflexion_sql(
                state.get("peticion") or "",
                state.get("borrador_final") or "",
                state.get("sql_final") or "",
                veredicto.motivos,
                previas,
            ),
            EVAL_MODEL,
            fallback=Reflexion(
                diagnostico="; ".join(veredicto.motivos) or "Respuesta incoherente",
                plan=(
                    "Reescribe el SQL usando periodos vía matriculas→ofertas; "
                    "no uses anio_ingreso salvo que pidan cohorte de ingreso."
                ),
                regla_general=(
                    "Expresiones temporales relativas se resuelven con periodos "
                    "y matrículas, no con anio_ingreso."
                ),
            ),
        )
        nueva = leccion(n, r)
        feedback = (
            f"Error: validación rechazó tu respuesta. {nueva} "
            "NO llames a SubmitFinalAnswer todavía. Propón una nueva consulta "
            "con ProponerConsultaSQL aplicando el plan."
        )
        return {
            "lecciones": previas + [nueva],
            "messages": [AIMessage(content=feedback)],
        }

    def aclaracion_humana(state: State) -> dict:
        raw = state.get("veredicto") or {}
        veredicto = VeredictoSql.model_validate(raw) if raw else VeredictoSql(
            aprobado=False,
            necesita_aclaracion=True,
            motivos=["Ambigüedad"],
            pregunta_aclaracion=(
                "¿Puedes aclarar el filtro temporal o de matrícula que necesitas?"
            ),
        )
        payload = PayloadAclaracionSql(
            pregunta_original=state.get("peticion") or "",
            borrador_respuesta=state.get("borrador_final") or "",
            sql_propuesto=state.get("sql_final") or None,
            motivos=veredicto.motivos,
            pregunta_aclaracion=veredicto.pregunta_aclaracion
            or "¿Puedes aclarar qué periodo o cohorte quieres consultar?",
        )
        decision = interrupt(dump_state(payload))
        # `decision` puede ser str o dict {aclaracion: "..."}
        if isinstance(decision, dict):
            texto = str(
                decision.get("aclaracion")
                or decision.get("texto")
                or decision.get("decision")
                or decision
            )
        else:
            texto = str(decision)

        leccion_humana = (
            f"Aclaración humana: {texto}. "
            f"Pregunta del agente: {payload.pregunta_aclaracion}"
        )
        memoria_sql.archivar(
            tenant,
            state.get("peticion") or payload.pregunta_original,
            texto,
            leccion=leccion_humana,
            sql_correcto="",
        )
        clarificaciones = list(state.get("clarificaciones") or [])
        clarificaciones.append(
            f"Petición parecida: {payload.pregunta_original}\n"
            f"Aclaración: {texto}\nLección: {leccion_humana}"
        )
        lecciones = list(state.get("lecciones") or []) + [leccion_humana]
        return {
            "messages": [
                HumanMessage(
                    content=(
                        f"Aclaración del docente: {texto}\n"
                        "Reescribe la consulta SQL respetando esta aclaración y "
                        "vuelve a responder con evidencia de la base de datos."
                    )
                )
            ],
            "clarificaciones": clarificaciones,
            "lecciones": lecciones,
            # Reinicia el contador de validación tras aclarar, para un nuevo ciclo limpio.
            "intentos_validacion": 0,
        }

    def should_continue(
        state: State,
    ) -> Literal[
        "validar_respuesta",
        "correct_query",
        "query_gen",
        "retry_agotado",
        "exigir_consulta",
        "__end__",
    ]:
        if state.get("retry_count", 0) >= MAX_SQL_AGENT_ITERACIONES:
            return "retry_agotado"
        last_message = state["messages"][-1]
        tool_calls = getattr(last_message, "tool_calls", None) or []
        nombres = {tc.get("name") for tc in tool_calls}
        if "SubmitFinalAnswer" in nombres:
            # Ya emitida tras validación OK → terminar
            if any(tc.get("id") == "tool_emitir_validado" for tc in tool_calls):
                return END
            if any(tc.get("id") == "tool_retry_agotado" for tc in tool_calls):
                return END
            if state.get("queries_ok", 0) < 1:
                return "exigir_consulta"
            return "validar_respuesta"
        if "ProponerConsultaSQL" in nombres:
            return "correct_query"
        if isinstance(last_message.content, str) and last_message.content.startswith("Error:"):
            return "query_gen"
        return "correct_query"

    grafo = StateGraph(State)
    grafo.add_node("list_tables_tool", create_tool_node_with_fallback([list_tables_tool]))
    grafo.add_node("model_get_schema", model_get_schema)
    grafo.add_node("get_schema_tool", create_tool_node_with_fallback([schema_tool]))
    grafo.add_node("cargar_memoria", cargar_memoria)
    grafo.add_node("query_gen", query_gen)
    grafo.add_node("correct_query", correct_query)
    grafo.add_node("execute_query", create_tool_node_with_fallback([db_query_tool]))
    grafo.add_node("retry_agotado", retry_agotado)
    grafo.add_node("primer_llamado", primer_llamado)
    grafo.add_node("exigir_consulta", exigir_consulta)
    grafo.add_node("validar_respuesta", validar_respuesta)
    grafo.add_node("emitir_respuesta", emitir_respuesta)
    grafo.add_node("reflexionar", reflexionar)
    grafo.add_node("aclaracion_humana", aclaracion_humana)

    grafo.add_edge(START, "primer_llamado")
    grafo.add_edge("primer_llamado", "list_tables_tool")
    grafo.add_edge("list_tables_tool", "model_get_schema")
    grafo.add_edge("model_get_schema", "get_schema_tool")
    grafo.add_edge("get_schema_tool", "cargar_memoria")
    grafo.add_edge("cargar_memoria", "query_gen")
    grafo.add_conditional_edges(
        "query_gen",
        should_continue,
        {
            END: END,
            "validar_respuesta": "validar_respuesta",
            "correct_query": "correct_query",
            "query_gen": "query_gen",
            "retry_agotado": "retry_agotado",
            "exigir_consulta": "exigir_consulta",
        },
    )
    grafo.add_conditional_edges(
        "validar_respuesta",
        tras_validar,
        {
            "emitir_respuesta": "emitir_respuesta",
            "aclaracion_humana": "aclaracion_humana",
            "reflexionar": "reflexionar",
        },
    )
    grafo.add_edge("emitir_respuesta", END)
    grafo.add_edge("reflexionar", "query_gen")
    grafo.add_edge("aclaracion_humana", "query_gen")
    grafo.add_edge("correct_query", "execute_query")
    grafo.add_edge("execute_query", "query_gen")
    grafo.add_edge("exigir_consulta", "query_gen")
    grafo.add_edge("retry_agotado", END)

    return grafo.compile(checkpointer=checkpointer or MemorySaver())
