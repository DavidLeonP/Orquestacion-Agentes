"""Grafo del orquestador con Reflexion + HITL, con LLMs y agentes falsos (sin red).

También comprueba que la evidencia (fuentes vistas) se llena cuando las tools RAG
reales se ejecutan dentro de un agente real (crear_agente) con un chat model falso.
"""

from __future__ import annotations


import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.types import Command

from src.agents import base as agents_base
from src.agents.schemas import (
    CriteriosRubrica,
    ConstraintsExamen,
    DecisionRouter,
    ExamenGenerado,
    PreguntaExamen,
    Reflexion,
    VeredictoValidacion,
)
from src.orchestrator import graph as grafo_mod
from src.rag import context as rag_context
from src.rag import tools as rag_tools

PETICION = "Genera un examen de 2 preguntas sobre la ley de Ohm"


def _examen(n: int, *, num=2, fuentes=("apuntes.txt",)) -> ExamenGenerado:
    return ExamenGenerado(
        preguntas=[
            PreguntaExamen(numero=i, enunciado=f"ENUNCIADO_{n}_{i}", puntuacion=10 / num, solucion="s")
            for i in range(1, num + 1)
        ],
        fuentes=list(fuentes),
    )


class Falsos:
    """Guion de un caso: exámenes y veredictos por intento, y registro de llamadas."""

    def __init__(self, examenes, veredictos, fuentes_tools=("apuntes.txt",), router="tutor"):
        self.examenes = list(examenes)
        self.veredictos = list(veredictos)
        self.fuentes_tools = list(fuentes_tools)
        self.router = router
        self.criterios = CriteriosRubrica()  # por defecto la rúbrica no exige nada
        self.llamadas_agente: list[tuple[str, str]] = []
        self.llamadas_llm: list[tuple[str, str]] = []
        self.archivados: list[tuple] = []
        self.recordados: list[tuple] = []
        self.guardados: list[tuple] = []

    # get_structured_model(schema, temperature=..., model=...)
    def get_structured_model(self, schema, **kwargs):
        falsos = self

        class Modelo:
            def invoke(self, prompt):
                falsos.llamadas_llm.append((schema.__name__, prompt))
                if schema is DecisionRouter:
                    return DecisionRouter(agente=falsos.router)
                if schema is ConstraintsExamen:
                    return ConstraintsExamen(num_preguntas=2, puntuacion_total=10)
                if schema is Reflexion:
                    n = sum(1 for s, _ in falsos.llamadas_llm if s == "Reflexion")
                    return Reflexion(
                        diagnostico=f"LECCION_{n} no consultó rúbricas.",
                        plan="Buscar con buscar_rubricas.",
                        regla_general="Consulta siempre las rúbricas.",
                    )
                raise AssertionError(schema)

        return Modelo()

    def ejecutar_agente(self, agente, peticion, nombre="agente"):
        self.llamadas_agente.append((nombre, peticion))
        if nombre == "exam_generator":
            rag_context.anotar_fuentes(self.fuentes_tools)  # como harían las tools RAG
            n = self.num_llamadas("exam_generator")
            return f"BORRADOR_INTENTO_{n}"
        return f"SALIDA_{nombre}"

    def estructurar_salida(self, esquema, texto, *, instruccion, nombre="estructurar"):
        if esquema is ExamenGenerado:
            return self.examenes.pop(0).model_copy(deep=True), True
        if esquema is VeredictoValidacion:
            return self.veredictos.pop(0).model_copy(deep=True), True
        raise AssertionError(esquema)

    def num_llamadas(self, nombre):
        return sum(1 for n, _ in self.llamadas_agente if n == nombre)

    def prompts(self, nombre):
        return [p for n, p in self.llamadas_agente if n == nombre]

    def llm(self, schema):
        return [p for s, p in self.llamadas_llm if s == schema]


class Store:
    def __init__(self, falsos):
        self.falsos = falsos

    def guardar(self, espacio, registro):
        self.falsos.guardados.append((espacio, registro))

    def perfil_de_alumno(self, alumno_id):
        return f"PERFIL {alumno_id}"


@pytest.fixture
def montar(monkeypatch):
    tokens = []

    def _montar(falsos: Falsos, user_id: int | None = 7):
        monkeypatch.setattr(grafo_mod, "get_structured_model", falsos.get_structured_model)
        monkeypatch.setattr(
            grafo_mod, "invocar_estructurado",
            lambda schema, prompt, model, fallback: falsos.get_structured_model(schema).invoke(prompt),
        )
        monkeypatch.setattr(grafo_mod, "cargar_criterios", lambda uid: falsos.criterios)
        for nombre in ("curriculum", "exam_generator", "rubric", "tutor"):
            monkeypatch.setattr(grafo_mod, f"crear_{nombre}_agent", lambda n=nombre: f"agente:{n}")
        monkeypatch.setattr(grafo_mod, "ejecutar_agente", falsos.ejecutar_agente)
        monkeypatch.setattr(grafo_mod, "estructurar_salida", falsos.estructurar_salida)
        monkeypatch.setattr(grafo_mod, "registrar_evento", lambda *a, **k: None)

        class Casos:
            def recordar(self, uid, peticion, k=2):
                falsos.recordados.append((uid, peticion))
                return ["CASO_PARECIDO"]

            def archivar(self, uid, peticion, contenido):
                falsos.archivados.append((uid, peticion, contenido))

        class Reglas:
            def cargar(self, agente):
                return ["REGLA_APRENDIDA"] if agente == "exam_generator" else []

        monkeypatch.setattr(grafo_mod, "memoria_casos", Casos())
        monkeypatch.setattr(grafo_mod, "manual_reglas", Reglas())
        if user_id is not None:
            tokens.append(rag_context.set_rag_user_id(user_id))
        return grafo_mod.construir_grafo(memory_backend=Store(falsos))

    yield _montar
    for t in reversed(tokens):
        rag_context.reset_rag_user_id(t)


CFG = {"configurable": {"thread_id": "t1"}}


def _interrupcion(grafo):
    estado = grafo.get_state(CFG)
    (tarea,) = [t for t in estado.tasks if t.interrupts]
    assert tarea.name == "aprobacion_docente"
    return tarea.interrupts[0].value


def _rechazo(motivo):
    return VeredictoValidacion(aprobado=False, motivos=[motivo], resumen=motivo)


def test_ciclo_reflexion_dos_intentos_y_hitl(montar):
    f = Falsos(
        examenes=[_examen(1), _examen(2)],
        veredictos=[_rechazo("Falta pregunta de seguridad"), VeredictoValidacion(aprobado=True)],
    )
    grafo = montar(f)
    grafo.invoke({"peticion": PETICION, "rol_usuario": "docente"}, CFG)

    # Router por regla: no se llamó al LLM router; sí a constraints
    assert f.llm("DecisionRouter") == []
    assert len(f.llm("ConstraintsExamen")) == 1

    # Dos intentos del Actor, dos validaciones del rubric y una reflexión
    assert f.num_llamadas("exam_generator") == 2
    assert f.num_llamadas("rubric_validacion") == 2
    assert len(f.llm("Reflexion")) == 1

    p1, p2 = f.prompts("exam_generator")
    assert "REGLA_APRENDIDA" in p1 and "CASO_PARECIDO" in p1
    assert "LECCION_1" not in p1
    # La lección llega al intento 2 ...
    assert "LECCION_1 no consultó rúbricas." in p2
    assert "REGLA_APRENDIDA" in p2 and "CASO_PARECIDO" in p2
    # ... y como lo rechazó el Rubric Agent (borrador aprovechable), el intento 2
    # REPARA: lleva los motivos y el borrador rechazado
    assert "CORRIGE este borrador" in p2 and "- Falta pregunta de seguridad" in p2
    assert p2.rstrip().endswith("BORRADOR:\nBORRADOR_INTENTO_1")
    # El reflector sí ve el borrador rechazado y el motivo
    (pr,) = f.llm("Reflexion")
    assert "BORRADOR_INTENTO_1" in pr and "Falta pregunta de seguridad" in pr

    # La memoria de casos se consulta una sola vez por petición (queda en el estado)
    assert f.recordados == [(7, PETICION)]

    payload = _interrupcion(grafo)
    assert payload["borrador"] == "BORRADOR_INTENTO_2"
    assert payload["veredicto"]["aprobado"] is True
    assert f.archivados == []  # nada se archiva antes del visto bueno

    final = grafo.invoke(Command(resume="si"), CFG)
    assert final["respuesta_final"] == "BORRADOR_INTENTO_2"
    assert f.archivados == [(7, PETICION, "BORRADOR_INTENTO_2")]
    assert [e for e, _ in f.guardados] == ["feedback_docente", "historico_generaciones"]
    assert final["reglas_nuevas"] == ["Consulta siempre las rúbricas."]
    assert len(final["intentos"]) == 2


def test_aprobado_a_la_primera_no_reflexiona(montar):
    f = Falsos(examenes=[_examen(1)], veredictos=[VeredictoValidacion(aprobado=True)])
    grafo = montar(f)
    grafo.invoke({"peticion": PETICION, "rol_usuario": "docente"}, CFG)
    assert f.num_llamadas("exam_generator") == 1
    assert f.llm("Reflexion") == []
    assert _interrupcion(grafo)["borrador"] == "BORRADOR_INTENTO_1"


def test_a_hitl_va_el_mejor_intento_no_el_ultimo(montar):
    # Intento 1: pasa lo determinista y lo rechaza el rubric.
    # Intento 2: empeora (3 preguntas) -> falla en etapa determinista.
    f = Falsos(
        examenes=[_examen(1), _examen(2, num=3)],
        veredictos=[_rechazo("Dificultad baja")],
    )
    grafo = montar(f)
    grafo.invoke({"peticion": PETICION, "rol_usuario": "docente"}, CFG)
    assert f.num_llamadas("rubric_validacion") == 1  # el intento 2 no llega al rubric
    payload = _interrupcion(grafo)
    assert payload["borrador"] == "BORRADOR_INTENTO_1"
    assert payload["veredicto"]["etapa"] == "llm"

    final = grafo.invoke(Command(resume="no"), CFG)
    assert "descartado" in final["respuesta_final"]
    assert f.archivados == []
    assert f.guardados == []


def test_fuente_no_consultada_falla_en_etapa_determinista(montar):
    f = Falsos(
        examenes=[_examen(1, fuentes=["inventado.pdf"]), _examen(2, fuentes=["Apuntes: apuntes.txt", "otro.pdf"])],
        veredictos=[],
        fuentes_tools=["apuntes.txt"],
    )
    grafo = montar(f)
    final = grafo.invoke({"peticion": PETICION, "rol_usuario": "docente"}, CFG)
    assert f.num_llamadas("rubric_validacion") == 0
    intentos = final["intentos"]
    assert len(intentos) == 2
    for intento, falsa in zip(intentos, ["inventado.pdf", "otro.pdf"]):
        assert intento["veredicto"]["etapa"] == "determinista"
        assert intento["veredicto"]["aprobado"] is False
        assert any(falsa in m and "no consultó" in m for m in intento["veredicto"]["motivos"])
    # "Apuntes: apuntes.txt" sí se acepta como cita de apuntes.txt
    assert not any("Apuntes: apuntes.txt" in m for m in intentos[1]["errores"])
    assert final["fuentes_vistas"] == ["apuntes.txt"]
    # La lección del intento 1 menciona el motivo determinista
    assert "inventado.pdf" in f.llm("Reflexion")[0]


def test_resume_si_archiva_una_sola_vez(montar):
    f = Falsos(examenes=[_examen(1)], veredictos=[VeredictoValidacion(aprobado=True)])
    grafo = montar(f)
    grafo.invoke({"peticion": PETICION, "rol_usuario": "docente"}, CFG)
    grafo.invoke(Command(resume="sí"), CFG)
    assert len(f.archivados) == 1
    # Reanudar de nuevo el hilo terminado no vuelve a archivar
    grafo.invoke(Command(resume="si"), CFG)
    assert len(f.archivados) == 1


def test_sin_user_id_no_usa_memoria_de_casos(montar):
    f = Falsos(examenes=[_examen(1)], veredictos=[VeredictoValidacion(aprobado=True)])
    grafo = montar(f, user_id=None)
    grafo.invoke({"peticion": PETICION, "rol_usuario": "docente"}, CFG)
    grafo.invoke(Command(resume="si"), CFG)
    assert f.recordados == [] and f.archivados == []
    assert "CASO_PARECIDO" not in f.prompts("exam_generator")[0]


def test_peticion_ambigua_usa_llm_router(montar):
    f = Falsos(examenes=[], veredictos=[], router="rubric")
    grafo = montar(f)
    final = grafo.invoke({"peticion": "Crea examen y rúbrica", "rol_usuario": "docente"}, CFG)
    assert len(f.llm("DecisionRouter")) == 1
    assert final["agente_destino"] == "rubric"
    assert final["respuesta_final"] == "SALIDA_rubric"


@pytest.mark.parametrize(
    "peticion, destino",
    [("Estructura la unidad 3 en sesiones", "curriculum"), ("Crea una rúbrica de evaluación", "rubric")],
)
def test_router_por_regla_no_llama_al_llm(montar, peticion, destino):
    f = Falsos(examenes=[], veredictos=[])
    grafo = montar(f)
    final = grafo.invoke({"peticion": peticion, "rol_usuario": "docente"}, CFG)
    assert f.llamadas_llm == []
    assert final["agente_destino"] == destino
    assert final["respuesta_final"] == f"SALIDA_{destino}"


def test_alumno_va_al_tutor_aunque_pida_un_examen(montar):
    f = Falsos(examenes=[], veredictos=[])
    grafo = montar(f)
    final = grafo.invoke(
        {"peticion": "Genera un examen de Ohm para practicar", "rol_usuario": "alumno", "alumno_id": "a1"}, CFG
    )
    assert f.llamadas_llm == []
    assert final["agente_destino"] == "tutor"
    (p,) = f.prompts("tutor")
    assert p.startswith("PERFIL a1")


# --- Evidencia por la ruta real: crear_exam_generator_agent + ejecutar_agente ---


class ChatFalsoConTools(GenericFakeChatModel):
    """GenericFakeChatModel no implementa bind_tools; create_agent lo exige."""

    def bind_tools(self, tools, **kwargs):
        return self


class RetrieverFalso:
    def __init__(self, indice):
        self.indice = indice

    def buscar(self, consulta):
        return [
            {"texto": f"texto {self.indice}", "metadatos": {"fuente": f"{self.indice}_1.txt"}},
            {"texto": "repetido", "metadatos": {"fuente": "comun.txt"}},
        ]


def test_evidencia_se_llena_desde_tools_en_agente_real(monkeypatch):
    from src.agents.exam_generator import crear_exam_generator_agent

    usuarios = []

    def _retriever(uid, indice):
        usuarios.append(uid)
        return RetrieverFalso(indice)

    monkeypatch.setattr(rag_tools, "obtener_retriever", _retriever)
    monkeypatch.setattr(rag_tools, "registrar_evento", lambda *a, **k: None)
    monkeypatch.setattr(agents_base, "registrar_evento", lambda *a, **k: None)
    llm = ChatFalsoConTools(
        messages=iter(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "buscar_apuntes", "args": {"consulta": "ohm"}, "id": "c1"},
                        {"name": "buscar_rubricas", "args": {"consulta": "criterios"}, "id": "c2"},
                    ],
                ),
                AIMessage(content="", tool_calls=[{"name": "buscar_examenes_historicos", "args": {"consulta": "x"}, "id": "c3"}]),
                AIMessage(content="Examen final.\nFuentes consultadas: apuntes_1.txt"),
            ]
        )
    )
    monkeypatch.setattr(agents_base, "get_chat_model", lambda **k: llm)
    agente = crear_exam_generator_agent()
    token = rag_context.set_rag_user_id(5)
    try:
        vistas = rag_context.iniciar_evidencia()
        respuesta = agents_base.ejecutar_agente(agente, "Genera un examen", "exam_generator")
    finally:
        rag_context.reset_rag_user_id(token)
    assert respuesta.startswith("Examen final.")
    # Las tools corren en el executor del ToolNode (contexto copiado) y aun así anotan
    assert sorted(vistas) == ["apuntes_1.txt", "comun.txt", "examenes_1.txt", "rubricas_1.txt"]
    assert vistas.count("comun.txt") == 1
    assert usuarios == [5, 5, 5]  # el user_id del contexto llega a las tools


def test_anotar_fuentes_sin_evidencia_iniciada_no_falla():
    import contextvars

    def _fuera():
        rag_context.anotar_fuentes(["a.txt"])  # no hay lista activa: no-op
        assert rag_context.rag_user_id_actual() is None

    contextvars.Context().run(_fuera)


# Regresión (graph.py, router): el estado de Reflexion (intentos, lecciones, casos,
# fuentes_vistas, reglas_nuevas) se reinicia en cada petición del mismo thread_id.
def test_segunda_peticion_mismo_thread_empieza_limpia(montar):
    f = Falsos(
        examenes=[_examen(1), _examen(2), _examen(3)],
        veredictos=[_rechazo("R1"), VeredictoValidacion(aprobado=True), VeredictoValidacion(aprobado=True)],
    )
    grafo = montar(f)
    grafo.invoke({"peticion": PETICION, "rol_usuario": "docente"}, CFG)
    grafo.invoke(Command(resume="si"), CFG)

    otra = "Genera un examen de 2 preguntas sobre palancas"
    grafo.invoke({"peticion": otra, "rol_usuario": "docente"}, CFG)
    p3 = f.prompts("exam_generator")[-1]
    assert "LECCION_1" not in p3  # las lecciones eran de la petición anterior
    assert f.recordados[-1] == (7, otra)  # casos recordados para la nueva petición
    payload = _interrupcion(grafo)
    assert payload["borrador"] == "BORRADOR_INTENTO_3"
    valores = grafo.get_state(CFG).values
    assert len(valores["intentos"]) == 1
    assert valores["lecciones"] == [] and valores["reglas_nuevas"] == []
    grafo.invoke(Command(resume="si"), CFG)
    assert [a[1] for a in f.archivados] == [PETICION, otra]
    assert f.archivados[1][2] == "BORRADOR_INTENTO_3"


def test_peticion_de_tutor_tras_examen_no_arrastra_intentos(montar):
    f = Falsos(examenes=[_examen(1)], veredictos=[VeredictoValidacion(aprobado=True)])
    grafo = montar(f)
    grafo.invoke({"peticion": PETICION, "rol_usuario": "docente"}, CFG)
    grafo.invoke(Command(resume="si"), CFG)
    final = grafo.invoke({"peticion": "Duda", "rol_usuario": "alumno"}, CFG)
    assert final["respuesta_final"] == "SALIDA_tutor"
    assert final["intentos"] == [] and final["casos"] == []


# --- Ronda 4: criterios de la rúbrica y modo reparar/regenerar ----------------------

from src.agents.schemas import CriteriosRubrica  # noqa: E402


def _examen_tipos(n, tipos, fuentes=("apuntes.txt",)):
    return ExamenGenerado(
        preguntas=[
            PreguntaExamen(numero=i, enunciado=f"ENUNCIADO_{n}_{i}", puntuacion=10 / len(tipos),
                           solucion="s", tipo=t)
            for i, t in enumerate(tipos, 1)
        ],
        fuentes=list(fuentes),
    )


def test_error_de_fuentes_regenera_sin_borrador(montar):
    f = Falsos(
        examenes=[_examen(1, fuentes=["inventado.pdf"]), _examen(2)],
        veredictos=[VeredictoValidacion(aprobado=True)],
    )
    grafo = montar(f)
    grafo.invoke({"peticion": PETICION, "rol_usuario": "docente"}, CFG)
    p1, p2 = f.prompts("exam_generator")
    assert "LECCION_1" in p2
    assert "CORRIGE este borrador" not in p2 and "BORRADOR_INTENTO_1" not in p2
    assert grafo.get_state(CFG).values["modo"] == "regenerar"


def test_falta_seguridad_rechazo_determinista_y_reparacion(montar):
    f = Falsos(
        examenes=[_examen_tipos(1, ["definicion", "numerico"]), _examen_tipos(2, ["numerico", "seguridad"])],
        veredictos=[VeredictoValidacion(aprobado=True)],
    )
    f.criterios = CriteriosRubrica(requiere_seguridad=True)
    grafo = montar(f)
    grafo.invoke({"peticion": PETICION, "rol_usuario": "docente"}, CFG)
    estado = grafo.get_state(CFG).values
    i1, i2 = estado["intentos"]
    assert i1["veredicto"]["etapa"] == "determinista"
    assert any("seguridad" in m for m in i1["veredicto"]["motivos"])
    # El Rubric Agent solo se llama para el intento 2 (el 1 no pasó lo determinista)
    assert f.num_llamadas("rubric_validacion") == 1
    assert estado["modo"] == "reparar"
    p2 = f.prompts("exam_generator")[1]
    assert "CORRIGE este borrador" in p2 and "seguridad" in p2 and "BORRADOR_INTENTO_1" in p2
    assert i2["veredicto"]["aprobado"] is True
    assert estado["criterios"]["requiere_seguridad"] is True


def test_reparar_precarga_las_fuentes_del_intento_previo(montar):
    class SinToolsEnReparacion(Falsos):
        def ejecutar_agente(self, agente, peticion, nombre="agente"):
            if nombre == "exam_generator" and self.num_llamadas("exam_generator") == 1:
                self.fuentes_tools = []  # al reparar, el agente no vuelve a buscar
            return super().ejecutar_agente(agente, peticion, nombre)

    f = SinToolsEnReparacion(
        examenes=[_examen(1), _examen(2)],
        veredictos=[_rechazo("Dificultad baja"), VeredictoValidacion(aprobado=True)],
        fuentes_tools=["apuntes.txt"],
    )
    grafo = montar(f)
    grafo.invoke({"peticion": PETICION, "rol_usuario": "docente"}, CFG)
    i1, i2 = grafo.get_state(CFG).values["intentos"]
    # El intento 2 cita apuntes.txt sin volver a consultarla: vale por la precarga
    assert i2["fuentes"] == ["apuntes.txt"] and i2["errores"] == []
    assert i2["veredicto"]["aprobado"] is True


def test_regenerar_no_precarga_fuentes(montar):
    class SinTools2(Falsos):
        def ejecutar_agente(self, agente, peticion, nombre="agente"):
            if nombre == "exam_generator" and self.num_llamadas("exam_generator") == 1:
                self.fuentes_tools = []
            return super().ejecutar_agente(agente, peticion, nombre)

    f = SinTools2(examenes=[_examen(1, fuentes=["inventado.pdf"]), _examen(2)], veredictos=[])
    grafo = montar(f)
    grafo.invoke({"peticion": PETICION, "rol_usuario": "docente"}, CFG)
    i1, i2 = grafo.get_state(CFG).values["intentos"]
    assert i2["fuentes"] == []
    assert i2["errores"] == ["No consultó ninguna fuente con las herramientas."]


def test_criterios_y_modo_se_reinician_entre_peticiones(montar):
    f = Falsos(
        examenes=[_examen_tipos(1, ["numerico", "numerico"]), _examen_tipos(2, ["numerico", "seguridad"])],
        veredictos=[VeredictoValidacion(aprobado=True)],
    )
    f.criterios = CriteriosRubrica(requiere_seguridad=True)
    grafo = montar(f)
    grafo.invoke({"peticion": PETICION, "rol_usuario": "docente"}, CFG)
    grafo.invoke(Command(resume="si"), CFG)
    v = grafo.get_state(CFG).values
    assert v["modo"] == "reparar" and v["criterios"]["requiere_seguridad"] is True

    grafo.invoke({"peticion": "¿Qué es Ohm?", "rol_usuario": "alumno"}, CFG)
    v = grafo.get_state(CFG).values
    assert v["modo"] == "regenerar" and v["criterios"] == {}
    assert v["intentos"] == [] and v["lecciones"] == []


def test_sin_user_id_no_carga_criterios(montar, monkeypatch):
    f = Falsos(examenes=[_examen(1)], veredictos=[VeredictoValidacion(aprobado=True)])
    grafo = montar(f, user_id=None)
    monkeypatch.setattr(grafo_mod, "cargar_criterios", lambda uid: pytest.fail("no debía cargar criterios"))
    grafo.invoke({"peticion": PETICION, "rol_usuario": "docente"}, CFG)
    assert grafo.get_state(CFG).values["criterios"] == {}
