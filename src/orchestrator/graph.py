"""Orquestador supervisor (directrices de orquestación, docs/arquitectura.md §2).

La información compartida entre agentes viaja como contratos Pydantic
(serializados a dict en el estado). El LLM es sustituible; el routing usa
campos tipados (p. ej. veredicto.aprobado), no substrings del texto libre.
"""

from typing import Any, Literal, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from src.agents.base import estructurar_salida, ejecutar_agente
from src.agents.curriculum import crear_curriculum_agent
from src.agents.exam_generator import crear_exam_generator_agent
from src.agents.rubric import crear_rubric_agent
from src.agents.schemas import (
    ConstraintsExamen,
    DecisionRouter,
    ExamenGenerado,
    PayloadAprobacion,
    VeredictoValidacion,
    dump_state,
    render_examen,
    render_veredicto,
    safe_parse,
)
from src.agents.tutor import crear_tutor_agent
from src.llm import get_chat_model
from src.memory import store as default_store
from src.observability.trazas import registrar_evento

MAX_REINTENTOS_VALIDACION = 2


class EstadoOrquestador(TypedDict, total=False):
    peticion: str
    rol_usuario: Literal["docente", "alumno"]
    alumno_id: str
    agente_destino: str
    constraints: dict
    examen: dict
    borrador: str
    veredicto: dict
    intentos_validacion: int
    respuesta_final: str


def construir_grafo(checkpointer: Any = None, memory_backend: Any = None):
    store = memory_backend or default_store
    llm_router = get_chat_model(temperature=0).with_structured_output(DecisionRouter)
    llm_constraints = get_chat_model(temperature=0).with_structured_output(
        ConstraintsExamen
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
        out: dict[str, Any] = {
            "agente_destino": decision.agente,
            "intentos_validacion": 0,
        }
        if decision.agente == "exam_generator":
            try:
                constraints = llm_constraints.invoke(
                    "Extrae las constraints del examen a partir de esta petición. "
                    "Si falta un dato, usa valores razonables por defecto "
                    "(Tecnología, 3º ESO, 6 preguntas, 55 min, media, 10 puntos):\n\n"
                    f"{estado['peticion']}"
                )
                if not isinstance(constraints, ConstraintsExamen):
                    constraints, _ = safe_parse(ConstraintsExamen, constraints)
                out["constraints"] = dump_state(constraints)
            except Exception:  # noqa: BLE001
                out["constraints"] = dump_state(ConstraintsExamen())
        registrar_evento(
            "router",
            metodo="llm",
            agente_destino=decision.agente,
        )
        return out

    def nodo_curriculum(estado: EstadoOrquestador) -> dict:
        return {
            "borrador": ejecutar_agente(
                agentes["curriculum"], estado["peticion"], "curriculum"
            )
        }

    def nodo_exam_generator(estado: EstadoOrquestador) -> dict:
        peticion = estado["peticion"]
        constraints_data = estado.get("constraints")
        if constraints_data:
            constraints, _ = safe_parse(ConstraintsExamen, constraints_data)
            peticion += (
                "\n\nConstraints tipadas (respétalas):\n"
                f"{constraints.model_dump_json(indent=2)}"
            )

        veredicto_data = estado.get("veredicto")
        if veredicto_data:
            veredicto, _ = safe_parse(VeredictoValidacion, veredicto_data)
            if not veredicto.aprobado:
                motivos = "\n".join(f"- {m}" for m in veredicto.motivos) or veredicto.resumen
                peticion += (
                    "\n\nTu borrador anterior fue rechazado por el Rubric Agent. "
                    "Corrige estos incumplimientos tipados:\n"
                    f"{motivos}\n\nBorrador anterior:\n"
                    + estado.get("borrador", "")
                )

        texto = ejecutar_agente(
            agentes["exam_generator"], peticion, "exam_generator"
        )
        examen, ok = estructurar_salida(
            ExamenGenerado,
            texto,
            instruccion=(
                "Estructura el siguiente examen en el schema ExamenGenerado. "
                "Incluye preguntas numeradas con puntuación, solucionario y fuentes. "
                "Copia el texto completo legible en texto_completo."
            ),
            nombre="exam_estructurar",
        )
        if not examen.texto_completo.strip():
            examen.texto_completo = texto
        registrar_evento("examen_estructurado", ok=ok, num_preguntas=len(examen.preguntas))
        return {
            "examen": dump_state(examen),
            "borrador": render_examen(examen),
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
        borrador = estado.get("borrador") or ""
        if estado.get("examen"):
            examen, _ = safe_parse(ExamenGenerado, estado["examen"])
            borrador = render_examen(examen) or borrador

        texto = ejecutar_agente(
            agentes["rubric"],
            "Valida el siguiente examen contra las rúbricas y criterios de "
            "diseño del departamento. Indica si apruebas o requieres cambios, "
            "lista criterios evaluados y motivos concretos:\n\n"
            + borrador,
            "rubric_validacion",
        )
        veredicto, ok = estructurar_salida(
            VeredictoValidacion,
            texto,
            instruccion=(
                "Convierte la validación en VeredictoValidacion. "
                "aprobado=true solo si el material cumple los criterios; "
                "si hay dudas o incumplimientos, aprobado=false y rellena motivos."
            ),
            nombre="veredicto_estructurar",
        )
        registrar_evento(
            "validacion_cruzada",
            intento=estado.get("intentos_validacion", 0) + 1,
            aprobado=veredicto.aprobado,
            estructurado_ok=ok,
            veredicto_resumen=veredicto.resumen[:300] or render_veredicto(veredicto)[:300],
        )
        return {
            "veredicto": dump_state(veredicto),
            "borrador": borrador,
            "intentos_validacion": estado.get("intentos_validacion", 0) + 1,
        }

    def aprobacion_docente(estado: EstadoOrquestador) -> dict:
        veredicto, _ = safe_parse(
            VeredictoValidacion,
            estado.get("veredicto"),
            fallback=VeredictoValidacion(
                aprobado=False,
                motivos=["veredicto_ausente"],
                resumen="Sin veredicto tipado",
            ),
        )
        examen = None
        if estado.get("examen"):
            examen, _ = safe_parse(ExamenGenerado, estado["examen"])
        borrador = estado.get("borrador") or (render_examen(examen) if examen else "")
        payload = PayloadAprobacion(
            borrador=borrador,
            veredicto=veredicto,
            examen=examen,
        )
        decision = interrupt(dump_state(payload))
        aprobado = str(decision).strip().lower() in {"si", "sí", "s", "yes", "y"}
        registrar_evento(
            "aprobacion_docente",
            decision="aprobado" if aprobado else "rechazado",
        )
        if aprobado:
            store.guardar(
                "feedback_docente",
                {"peticion": estado["peticion"], "decision": "aprobado"},
            )
            store.guardar(
                "historico_generaciones",
                {"tipo": "examen", "contenido": borrador},
            )
            return {"respuesta_final": borrador}
        return {
            "respuesta_final": (
                "Material descartado por el docente. Vuelve a pedirlo indicando "
                "qué quieres cambiar.\n\nBorrador descartado:\n" + borrador
            )
        }

    def finalizar(estado: EstadoOrquestador) -> dict:
        return {"respuesta_final": estado["borrador"]}

    def ruta_desde_router(estado: EstadoOrquestador) -> str:
        return estado["agente_destino"]

    def ruta_tras_validacion(estado: EstadoOrquestador) -> str:
        veredicto, ok = safe_parse(
            VeredictoValidacion,
            estado.get("veredicto"),
            fallback=VeredictoValidacion(
                aprobado=False,
                motivos=["salida_no_estructurada"],
                resumen="Veredicto inválido en estado",
            ),
        )
        if not ok:
            registrar_evento("routing_veredicto_invalido", motivos=veredicto.motivos)
        if veredicto.aprobado:
            return "aprobacion_docente"
        if estado.get("intentos_validacion", 0) >= MAX_REINTENTOS_VALIDACION:
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
