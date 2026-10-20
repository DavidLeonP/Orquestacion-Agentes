"""Orquestador supervisor (directrices de orquestación, docs/arquitectura.md §2).

La información compartida entre agentes viaja como contratos Pydantic
(serializados a dict en el estado). El LLM es sustituible; el routing usa
campos tipados (p. ej. veredicto.aprobado), no substrings del texto libre.

Generación de exámenes con Reflexion (§5.4): exam_generator -> validar ->
reflexionar -> exam_generator, hasta MAX_INTENTOS; al docente va el mejor
intento. Las decisiones puras viven en `reflexion.py`.
"""

from typing import Any, Literal, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from src.agents.base import ejecutar_agente, estructurar_salida, invocar_estructurado
from src.agents.curriculum import crear_curriculum_agent
from src.agents.exam_generator import crear_exam_generator_agent
from src.agents.rubric import crear_rubric_agent
from src.agents.schemas import (
    ConstraintsExamen,
    CriteriosRubrica,
    DecisionRouter,
    ExamenGenerado,
    PayloadAprobacion,
    Reflexion,
    VeredictoValidacion,
    dump_state,
    render_examen,
    render_veredicto,
    safe_parse,
)
from src.agents.tutor import crear_tutor_agent
from src.config import EVAL_MODEL
from src.llm import get_structured_model
from src.memory import casos as memoria_casos
from src.memory import reglas as manual_reglas
from src.memory import store as default_store
from src.observability.trazas import registrar_evento
from src.orchestrator.criterios import cargar_criterios
from src.orchestrator.reflexion import (
    leccion,
    mejor_intento,
    modo_reintento,
    peticion_examen,
    prompt_reflexion,
    siguiente_paso,
    verificar_examen,
)
from src.orchestrator.routing import enrutar_por_reglas
from src.rag.context import iniciar_evidencia, rag_user_id_actual


class EstadoOrquestador(TypedDict, total=False):
    peticion: str
    rol_usuario: Literal["docente", "alumno"]
    alumno_id: str
    agente_destino: str
    constraints: dict
    examen: dict
    borrador: str
    fuentes_vistas: list[str]  # fuentes devueltas por las tools RAG en el intento actual
    casos: list[str]  # exámenes aprobados parecidos (memoria de casos)
    criterios: dict  # CriteriosRubrica de la rúbrica del docente ({} = sin criterios)
    intentos: list[dict]  # {examen, borrador, veredicto, errores, fuentes} por intento
    lecciones: list[str]  # Reflexion: una por intento rechazado
    modo: str  # siguiente intento: "regenerar" (Reflexion) o "reparar" (corrige el borrador)
    reglas_nuevas: list[str]  # Reflexion: reglas generales para el entrenamiento
    respuesta_final: str


# El router lo aplica en cada petición: un thread_id reutilizado (legacy_chat_api)
# no debe heredar intentos ni memoria de la petición anterior.
ESTADO_PETICION_NUEVA = {
    "fuentes_vistas": [],
    "casos": [],
    "criterios": {},
    "intentos": [],
    "lecciones": [],
    "modo": "regenerar",
    "reglas_nuevas": [],
}


def construir_grafo(checkpointer: Any = None, memory_backend: Any = None):
    store = memory_backend or default_store
    llm_router = get_structured_model(DecisionRouter, temperature=0)
    llm_constraints = get_structured_model(ConstraintsExamen, temperature=0)
    reglas_examen = manual_reglas.cargar("exam_generator")
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
            return {"agente_destino": destino, **ESTADO_PETICION_NUEVA}
        destino, metodo = enrutar_por_reglas(estado["peticion"]), "regla"
        if destino is None:
            metodo = "llm"
            decision = llm_router.invoke(
                "Clasifica a qué agente especializado corresponde esta petición de "
                "un docente. Elige EXACTAMENTE uno de: curriculum, exam_generator, "
                "rubric, tutor.\n"
                "Ejemplos:\n"
                "- 'Genera un examen de 6 preguntas' -> exam_generator\n"
                "- 'Estructura la unidad en sesiones' -> curriculum\n"
                "- 'Propón una rúbrica de evaluación' -> rubric\n"
                "- 'Explica la ley de Ohm con los apuntes' -> tutor\n"
                "- '¿Qué es un circuito en serie?' -> tutor\n\n"
                f"Petición:\n{estado['peticion']}"
            )
            # Fallback seguro si el LLM local no materializa el contrato.
            decision, _ = safe_parse(
                DecisionRouter, decision, fallback=DecisionRouter(agente="tutor")
            )
            destino = decision.agente
        out: dict[str, Any] = {"agente_destino": destino, **ESTADO_PETICION_NUEVA}
        if destino == "exam_generator":
            user_id = rag_user_id_actual()
            if user_id:
                out["casos"] = memoria_casos.recordar(user_id, estado["peticion"])
                out["criterios"] = dump_state(cargar_criterios(user_id))
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
        registrar_evento("router", metodo=metodo, agente_destino=destino)
        return out

    def nodo_curriculum(estado: EstadoOrquestador) -> dict:
        return {
            "borrador": ejecutar_agente(
                agentes["curriculum"], estado["peticion"], "curriculum"
            )
        }

    def _constraints(estado: EstadoOrquestador) -> ConstraintsExamen:
        return safe_parse(ConstraintsExamen, estado.get("constraints") or {})[0]

    def nodo_exam_generator(estado: EstadoOrquestador) -> dict:
        # Actor: memoria = reglas + casos + lecciones; al reparar, además el borrador rechazado
        casos = estado.get("casos", [])
        modo = estado.get("modo", "regenerar")
        reparar = estado["intentos"][-1] if modo == "reparar" else None
        peticion = peticion_examen(
            estado["peticion"],
            _constraints(estado),
            estado.get("lecciones", []),
            reglas=reglas_examen,
            casos=casos,
            reparar=reparar,
        )
        vistas = iniciar_evidencia()
        if reparar:
            # El borrador reparado puede seguir citando lo que se consultó al escribirlo
            vistas.extend(reparar["fuentes"])
        texto = ejecutar_agente(agentes["exam_generator"], peticion, "exam_generator")
        examen, ok = estructurar_salida(
            ExamenGenerado,
            texto,
            instruccion=(
                "Estructura el siguiente examen en el schema ExamenGenerado. "
                "Incluye preguntas numeradas con puntuación, solucionario y fuentes. "
                "Clasifica cada pregunta en `tipo`: definicion (teoría), numerico (cálculos), "
                "esquema (dibujo o diagrama), tabla, seguridad (normas de seguridad o "
                "protección, aunque tenga cálculos) u otro; y marca con_calculo=true si su "
                "respuesta exige cálculos, sea cual sea el tipo. "
                "Copia el texto completo legible en texto_completo."
            ),
            nombre="exam_estructurar",
        )
        if not examen.texto_completo.strip():
            examen.texto_completo = texto
        registrar_evento(
            "examen_estructurado",
            ok=ok,
            modo=modo,
            num_preguntas=len(examen.preguntas),
            tipos=[p.tipo for p in examen.preguntas],
            fuentes_vistas=vistas,
            casos=len(casos),
            reglas=len(reglas_examen),
        )
        return {
            "examen": dump_state(examen),
            "borrador": render_examen(examen),
            "fuentes_vistas": list(vistas),
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
        # Evaluador híbrido: reglas en Python primero; el LLM solo si pasan
        constraints = _constraints(estado)
        examen, _ = safe_parse(ExamenGenerado, estado["examen"])
        borrador = estado["borrador"]
        criterios = safe_parse(CriteriosRubrica, estado.get("criterios") or {})[0]
        errores = verificar_examen(examen, constraints, estado.get("fuentes_vistas"), criterios)
        if errores:
            veredicto = VeredictoValidacion(
                aprobado=False,
                motivos=errores,
                resumen="Incumple constraints o criterios de la rúbrica verificables.",
                etapa="determinista",
            )
        else:
            texto = ejecutar_agente(
                agentes["rubric"],
                "Valida el siguiente examen contra las rúbricas y criterios de "
                "diseño del departamento y contra estas constraints:\n"
                f"{constraints.model_dump_json(indent=2)}\n"
                "Cada motivo debe nombrar la pregunta y el criterio incumplido. "
                "No rechaces por 'falta verificar más' si las rúbricas consultadas "
                "respaldan el examen.\n\n" + borrador,
                "rubric_validacion",
            )
            veredicto, _ = estructurar_salida(
                VeredictoValidacion,
                texto,
                instruccion=(
                    "Convierte la validación en VeredictoValidacion. "
                    "aprobado=true solo si el material cumple los criterios; "
                    "si hay incumplimientos, aprobado=false y rellena motivos."
                ),
                nombre="veredicto_estructurar",
            )
            veredicto.etapa = "llm"
        intentos = estado.get("intentos", []) + [
            {
                "examen": estado["examen"],
                "borrador": borrador,
                "veredicto": dump_state(veredicto),
                "errores": errores,
                "fuentes": estado.get("fuentes_vistas", []),
            }
        ]
        registrar_evento(
            "validacion_cruzada",
            intento=len(intentos),
            etapa=veredicto.etapa,
            aprobado=veredicto.aprobado,
            veredicto_resumen=render_veredicto(veredicto)[:300],
        )
        return {"intentos": intentos}

    def reflexionar(estado: EstadoOrquestador) -> dict:
        # Auto-reflexión: convierte el rechazo en una lección y decide reparar o regenerar
        ultimo = estado["intentos"][-1]
        motivos = ultimo["veredicto"]["motivos"] or [ultimo["veredicto"]["resumen"]]
        previas = estado.get("lecciones", [])
        r = invocar_estructurado(
            Reflexion,
            prompt_reflexion(estado["peticion"], ultimo["borrador"], motivos, previas),
            EVAL_MODEL,
            Reflexion(diagnostico="; ".join(motivos), plan="Corrige esos incumplimientos antes de entregar."),
        )
        n, modo = len(estado["intentos"]), modo_reintento(ultimo)
        registrar_evento("reflexion", intento=n, modo=modo, diagnostico=r.diagnostico[:300], plan=r.plan[:300])
        # reglas_nuevas solo se consumen en el entrenamiento (scripts/entrenar_reglas.py)
        nuevas = estado.get("reglas_nuevas", []) + ([r.regla_general] if r.regla_general else [])
        return {"lecciones": previas + [leccion(n, r)], "reglas_nuevas": nuevas, "modo": modo}

    def aprobacion_docente(estado: EstadoOrquestador) -> dict:
        intentos = estado["intentos"]
        elegido = mejor_intento(intentos)
        borrador = elegido["borrador"]
        payload = PayloadAprobacion(
            borrador=borrador,
            veredicto=safe_parse(VeredictoValidacion, elegido["veredicto"])[0],
            examen=safe_parse(ExamenGenerado, elegido["examen"])[0],
        )
        decision = interrupt(dump_state(payload))
        aprobado = str(decision).strip().lower() in {"si", "sí", "s", "yes", "y"}
        registrar_evento(
            "aprobacion_docente",
            decision="aprobado" if aprobado else "rechazado",
            intento_elegido=intentos.index(elegido) + 1,
            intentos=len(intentos),
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
            if user_id := rag_user_id_actual():
                memoria_casos.archivar(user_id, estado["peticion"], borrador)
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

    grafo = StateGraph(EstadoOrquestador)
    grafo.add_node("router", router)
    grafo.add_node("curriculum", nodo_curriculum)
    grafo.add_node("exam_generator", nodo_exam_generator)
    grafo.add_node("rubric", nodo_rubric)
    grafo.add_node("tutor", nodo_tutor)
    grafo.add_node("validar", validar)
    grafo.add_node("reflexionar", reflexionar)
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
        "validar",
        lambda estado: siguiente_paso(estado["intentos"]),
        ["aprobacion_docente", "reflexionar"],
    )
    grafo.add_edge("reflexionar", "exam_generator")
    grafo.add_edge("curriculum", "finalizar")
    grafo.add_edge("rubric", "finalizar")
    grafo.add_edge("tutor", "finalizar")
    grafo.add_edge("aprobacion_docente", END)
    grafo.add_edge("finalizar", END)

    return grafo.compile(checkpointer=checkpointer or MemorySaver())
