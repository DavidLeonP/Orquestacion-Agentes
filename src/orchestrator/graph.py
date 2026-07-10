"""Orquestador supervisor (directrices de orquestación, docs/arquitectura.md §2)."""

from typing import Any, Literal, TypedDict

from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from src.agents.base import ejecutar_agente
from src.agents.curriculum import crear_curriculum_agent
from src.agents.exam_generator import crear_exam_generator_agent
from src.agents.rubric import crear_rubric_agent
from src.agents.schemas import DecisionRouter
from src.agents.tutor import crear_tutor_agent
from src.config import LLM_MODEL
from src.memory import store as default_store
from src.observability.trazas import registrar_evento

MAX_REINTENTOS_VALIDACION = 2


class EstadoOrquestador(TypedDict, total=False):
    peticion: str
    rol_usuario: Literal["docente", "alumno"]
    alumno_id: str
    agente_destino: str
    borrador: str
    veredicto: str
    intentos_validacion: int
    respuesta_final: str


def construir_grafo(checkpointer: Any = None, memory_backend: Any = None):
    store = memory_backend or default_store
    llm_router = ChatOpenAI(model=LLM_MODEL, temperature=0).with_structured_output(
        DecisionRouter
    )
    agentes = {
        "curriculum": crear_curriculum_agent(),
        "exam_generator": crear_exam_generator_agent(),
        "rubric": crear_rubric_agent(),
        "tutor": crear_tutor_agent(),
    }

    def router(estado: EstadoOrquestador) -> dict:
        if estado.get("rol_usuario") == "alumno":
            destino = "tutor"
            registrar_evento(
                "router",
                metodo="regla",
                agente_destino=destino,
                motivo="rol_usuario=alumno",
            )
            return {"agente_destino": destino, "intentos_validacion": 0}
        decision = llm_router.invoke(
            "Clasifica a qué agente especializado corresponde esta petición de "
            f"un docente:\n\n{estado['peticion']}"
        )
        registrar_evento(
            "router",
            metodo="llm",
            agente_destino=decision.agente,
        )
        return {"agente_destino": decision.agente, "intentos_validacion": 0}

    def nodo_curriculum(estado: EstadoOrquestador) -> dict:
        return {
            "borrador": ejecutar_agente(
                agentes["curriculum"], estado["peticion"], "curriculum"
            )
        }

    def nodo_exam_generator(estado: EstadoOrquestador) -> dict:
        peticion = estado["peticion"]
        if estado.get("veredicto") and "CAMBIOS REQUERIDOS" in estado["veredicto"]:
            peticion += (
                "\n\nTu borrador anterior fue rechazado por el Rubric Agent. "
                "Corrige estos incumplimientos:\n" + estado["veredicto"]
                + "\n\nBorrador anterior:\n" + estado.get("borrador", "")
            )
        return {
            "borrador": ejecutar_agente(
                agentes["exam_generator"], peticion, "exam_generator"
            )
        }

    def nodo_rubric(estado: EstadoOrquestador) -> dict:
        return {
            "borrador": ejecutar_agente(agentes["rubric"], estado["peticion"], "rubric")
        }

    def nodo_tutor(estado: EstadoOrquestador) -> dict:
        perfil = store.perfil_de_alumno(estado.get("alumno_id", "anonimo"))
        peticion = f"{perfil}\n\nPetición del alumno:\n{estado['peticion']}"
        return {
            "borrador": ejecutar_agente(agentes["tutor"], peticion, "tutor"),
        }

    def validar(estado: EstadoOrquestador) -> dict:
        veredicto = ejecutar_agente(
            agentes["rubric"],
            "Valida el siguiente examen contra las rúbricas y criterios de "
            "diseño del departamento:\n\n" + estado["borrador"],
            "rubric_validacion",
        )
        aprobado = "VEREDICTO: APROBADO" in veredicto.upper()
        registrar_evento(
            "validacion_cruzada",
            intento=estado.get("intentos_validacion", 0) + 1,
            aprobado=aprobado,
            veredicto_resumen=veredicto[:300],
        )
        return {
            "veredicto": veredicto,
            "intentos_validacion": estado.get("intentos_validacion", 0) + 1,
        }

    def aprobacion_docente(estado: EstadoOrquestador) -> dict:
        decision = interrupt(
            {
                "mensaje": "Examen validado. ¿Apruebas el material? (si/no)",
                "borrador": estado["borrador"],
                "veredicto": estado["veredicto"],
            }
        )
        aprobado = str(decision).strip().lower() in {"si", "sí", "s", "yes", "y"}
        registrar_evento("aprobacion_docente", decision="aprobado" if aprobado else "rechazado")
        if aprobado:
            store.guardar(
                "feedback_docente",
                {"peticion": estado["peticion"], "decision": "aprobado"},
            )
            store.guardar(
                "historico_generaciones",
                {"tipo": "examen", "contenido": estado["borrador"]},
            )
            return {"respuesta_final": estado["borrador"]}
        return {
            "respuesta_final": (
                "Material descartado por el docente. Vuelve a pedirlo indicando "
                "qué quieres cambiar.\n\nBorrador descartado:\n" + estado["borrador"]
            )
        }

    def finalizar(estado: EstadoOrquestador) -> dict:
        return {"respuesta_final": estado["borrador"]}

    def ruta_desde_router(estado: EstadoOrquestador) -> str:
        return estado["agente_destino"]

    def ruta_tras_validacion(estado: EstadoOrquestador) -> str:
        if "VEREDICTO: APROBADO" in estado["veredicto"].upper():
            return "aprobacion_docente"
        if estado["intentos_validacion"] >= MAX_REINTENTOS_VALIDACION:
            return "aprobacion_docente"
        return "exam_generator"

    grafo = StateGraph(EstadoOrquestador)
    grafo.add_node("router", router)
    grafo.add_node("curriculum", nodo_curriculum)
    grafo.add_node("exam_generator", nodo_exam_generator)
    grafo.add_node("rubric", nodo_rubric)
    grafo.add_node("tutor", nodo_tutor)
    grafo.add_node("validar", validar)
    grafo.add_node("aprobacion_docente", aprobacion_docente)
    grafo.add_node("finalizar", finalizar)

    grafo.add_edge(START, "router")
    grafo.add_conditional_edges(
        "router",
        ruta_desde_router,
        ["curriculum", "exam_generator", "rubric", "tutor"],
    )
    grafo.add_edge("exam_generator", "validar")
    grafo.add_conditional_edges(
        "validar", ruta_tras_validacion, ["aprobacion_docente", "exam_generator"]
    )
    grafo.add_edge("curriculum", "finalizar")
    grafo.add_edge("rubric", "finalizar")
    grafo.add_edge("tutor", "finalizar")
    grafo.add_edge("aprobacion_docente", END)
    grafo.add_edge("finalizar", END)

    return grafo.compile(checkpointer=checkpointer or MemorySaver())
