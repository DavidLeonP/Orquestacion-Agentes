"""Fase 4: conjuntos eval/, corrida, métricas, juez y entrenamiento del manual (sin red)."""

from __future__ import annotations

import importlib
import json
from types import SimpleNamespace

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from src.agents.schemas import DecisionRouter, Reflexion, VeredictoValidacion
from src.agents import base as agents_base
from src.evaluation import corrida, juez
from src.memory import reglas as manual_reglas
from src.orchestrator import graph as grafo_mod
from src.rag import context as rag_context
from tests.test_grafo_reflexion import PETICION, Falsos, _examen, _rechazo, montar  # noqa: F401

CONJUNTOS = ["entrenamiento", "prueba", "reservado"]
CLAVES = {"id", "tipo", "rol", "peticion", "agente_esperado", "referencia", "fuentes_esperadas"}
AGENTES = set(DecisionRouter.model_fields["agente"].annotation.__args__)


# --- Conjuntos eval/*.jsonl ----------------------------------------------------


@pytest.mark.parametrize("nombre", CONJUNTOS)
def test_conjunto_carga_con_claves_y_agentes_validos(nombre):
    items = corrida.cargar_conjunto(nombre)
    assert items
    for it in items:
        assert CLAVES <= set(it), (it.get("id"), CLAVES - set(it))
        assert it["agente_esperado"] in AGENTES, it["id"]
        assert it["rol"] in {"docente", "alumno"}, it["id"]
        assert it["peticion"].strip() and it["referencia"].strip(), it["id"]
        assert isinstance(it["fuentes_esperadas"], list)
        if it["rol"] == "alumno":
            assert it["agente_esperado"] == "tutor", it["id"]  # el router manda al alumno al tutor


def test_ids_unicos_entre_conjuntos():
    ids = [it["id"] for n in CONJUNTOS for it in corrida.cargar_conjunto(n)]
    assert len(ids) == len(set(ids))


def test_entrenamiento_tiene_examenes():
    assert any(i["agente_esperado"] == "exam_generator" for i in corrida.cargar_conjunto("entrenamiento"))


def test_peticiones_no_se_filtran_entre_conjuntos():
    # Evaluar con preguntas del entrenamiento invalidaría la evaluación
    pet = {n: {i["peticion"].strip().lower() for i in corrida.cargar_conjunto(n)} for n in CONJUNTOS}
    assert not pet["entrenamiento"] & pet["prueba"]
    assert not pet["entrenamiento"] & pet["reservado"]
    assert not pet["prueba"] & pet["reservado"]


# --- correr() con el grafo real y fakes ----------------------------------------


class FalsosConTokens(Falsos):
    """Además emite uso de tokens (vía un chat model falso) y anota fuentes del tutor."""

    def ejecutar_agente(self, agente, peticion, nombre="agente"):
        GenericFakeChatModel(
            messages=iter([AIMessage(
                content="x",
                usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                response_metadata={"model_name": "fake"},
            )])
        ).invoke("hola")
        if nombre == "tutor":
            rag_context.anotar_fuentes(["tutor_apuntes.txt"])
        return super().ejecutar_agente(agente, peticion, nombre)


def _item(peticion, rol="docente", id_="t1"):
    return {"id": id_, "peticion": peticion, "rol": rol}


def test_correr_examen_devuelve_borrador_hitl(montar):
    f = FalsosConTokens(
        examenes=[_examen(1), _examen(2, num=3)],
        veredictos=[_rechazo("Dificultad baja")],
        fuentes_tools=["apuntes.txt", "rubrica.md"],
    )
    app = montar(f, user_id=None)
    r = corrida.correr(app, _item(PETICION), user_id=7)
    assert r["id"] == "t1" and r["agente"] == "exam_generator"
    # Va el mejor intento (el 1), igual que en el HITL
    assert r["respuesta"] == "BORRADOR_INTENTO_1"
    assert r["intentos"] == 2
    assert r["errores_reglas"] == [] and r["aprobado_rubric"] is False
    assert r["fuentes"] == ["apuntes.txt", "rubrica.md"]
    assert r["reglas_nuevas"] == ["Consulta siempre las rúbricas."]
    assert isinstance(r["tokens"], int) and r["tokens"] == 15 * 3  # 2 exam_generator + 1 rubric
    assert isinstance(r["segundos"], float)
    # correr usa el user_id que recibe (la memoria de casos se consulta con él)...
    assert f.recordados == [(7, PETICION)]
    # ... y no reanuda el HITL: no se archiva nada
    assert f.archivados == []
    # El contexto queda limpio al salir
    assert rag_context.rag_user_id_actual() is None


def test_correr_tutor_devuelve_respuesta_final_y_fuentes_del_runner(montar):
    f = FalsosConTokens(examenes=[], veredictos=[])
    app = montar(f, user_id=None)
    r = corrida.correr(app, _item("¿Qué es la ley de Ohm?", rol="alumno"), user_id=7)
    assert r["agente"] == "tutor"
    assert r["respuesta"] == "SALIDA_tutor"
    assert r["fuentes"] == ["tutor_apuntes.txt"]
    assert r["intentos"] is None  # fuera de exámenes no cuenta en el promedio
    assert r["errores_reglas"] is None and r["aprobado_rubric"] is None
    assert r["tokens"] == 15


def test_correr_resetea_contexto_aunque_falle(montar):
    class Roto:
        def stream(self, *a, **k):
            raise RuntimeError("grafo roto")

    with pytest.raises(RuntimeError):
        corrida.correr(Roto(), _item("x"), user_id=7)
    assert rag_context.rag_user_id_actual() is None


class FuentesPorIntento(FalsosConTokens):
    """Las tools del exam_generator ven i1.txt en el intento 1 e i2.txt en el 2;
    el Rubric Agent (validar) ve rubrica_validar.md."""

    def ejecutar_agente(self, agente, peticion, nombre="agente"):
        if nombre == "exam_generator":
            self.fuentes_tools = ["i1.txt"] if self.num_llamadas("exam_generator") == 0 else ["i2.txt"]
        if nombre == "rubric_validacion":
            rag_context.anotar_fuentes(["rubrica_validar.md"])
        return super().ejecutar_agente(agente, peticion, nombre)


# Regresión (corrida.py): antes las fuentes eran las del ÚLTIMO intento y no las
# del intento entregado.
def test_correr_fuentes_son_las_del_intento_elegido(montar):
    f = FuentesPorIntento(
        examenes=[_examen(1, fuentes=["i1.txt"]), _examen(2, num=3, fuentes=["i2.txt"])],
        veredictos=[_rechazo("R")],
    )
    r = corrida.correr(montar(f, user_id=None), _item(PETICION), user_id=7)
    assert r["respuesta"] == "BORRADOR_INTENTO_1"
    assert "i2.txt" not in r["fuentes"]
    assert "i1.txt" in r["fuentes"]


# Regresión (corrida.py): antes las fuentes del Rubric Agent en `validar` inflaban
# el recall del examen.
def test_correr_examen_no_suma_fuentes_del_rubric(montar):
    f = FuentesPorIntento(examenes=[_examen(1, fuentes=["i1.txt"])], veredictos=[VeredictoValidacion(aprobado=True)])
    r = corrida.correr(montar(f, user_id=None), _item(PETICION), user_id=7)
    assert r["fuentes"] == ["i1.txt"]


def test_correr_excepcion_se_propaga(montar):
    # Comportamiento actual: un fallo del grafo aborta (evaluar/entrenar pierden el conjunto)
    class Roto(Falsos):
        def ejecutar_agente(self, agente, peticion, nombre="agente"):
            raise ConnectionError("LLM caído")

    app = montar(Roto(examenes=[], veredictos=[]), user_id=None)
    with pytest.raises(ConnectionError):
        corrida.correr(app, _item("¿Qué es Ohm?", rol="alumno"), user_id=7)
    assert rag_context.rag_user_id_actual() is None


# --- metricas / promedios / calibrar -------------------------------------------


def _juicio(p=0.5, paso=True):
    return juez.Juicio(puntaje=p, paso=paso, motivo="m")


def test_metricas_examen():
    item = {"agente_esperado": "exam_generator", "fuentes_esperadas": ["rubrica", "ohm", "nada"]}
    r = {"agente": "exam_generator", "fuentes": ["tec_rubrica.md", "apuntes_ohm.txt"], "errores_reglas": []}
    m = corrida.metricas(item, r, _juicio(0.8, True))
    assert m == {"agente_ok": True, "recall_fuentes": pytest.approx(2 / 3), "cumple_reglas": True,
                 "juez_puntaje": 0.8, "juez_paso": True}


def test_metricas_sin_fuentes_esperadas_ni_intentos():
    item = {"agente_esperado": "tutor", "fuentes_esperadas": []}
    r = {"agente": "curriculum", "fuentes": [], "errores_reglas": None}
    m = corrida.metricas(item, r, _juicio(0.0, False))
    assert m["agente_ok"] is False
    assert m["recall_fuentes"] is None and m["cumple_reglas"] is None
    assert corrida.metricas({"agente_esperado": "tutor"}, r, _juicio())["recall_fuentes"] is None


def test_metricas_incumple_reglas():
    r = {"agente": "exam_generator", "fuentes": [], "errores_reglas": ["suma"]}
    assert corrida.metricas({"agente_esperado": "exam_generator"}, r, _juicio())["cumple_reglas"] is False


def test_promedios_ignora_none():
    filas = [
        {"a": True, "b": None, "c": 10},
        {"a": False, "b": 0.5, "c": 20},
        {"a": True, "c": 30},
    ]
    assert corrida.promedios(filas, ["a", "b", "c", "d"]) == {"a": 0.667, "b": 0.5, "c": 20.0, "d": None}
    assert corrida.promedios([], ["a"]) == {"a": None}


def test_promedios_intentos_de_no_examenes_no_bajan_la_media():
    # correr() da intentos=None fuera de exámenes, así que no cuenta
    assert corrida.promedios([{"intentos": None}, {"intentos": 2}], ["intentos"]) == {"intentos": 2.0}


def test_calibrar():
    pares = [(True, True), (False, False), (True, False), (False, True), (True, False)]
    assert corrida.calibrar(pares) == {"aciertos": 2, "falsos_pass": 2, "falsos_fail": 1, "total": 5}
    assert corrida.calibrar([]) == {"aciertos": 0, "falsos_pass": 0, "falsos_fail": 0, "total": 0}


# --- Juez y consolidación ------------------------------------------------------


class ModeloFijo:
    def __init__(self, salida):
        self.salida = salida
        self.prompts = []
        self.kwargs = None

    def __call__(self, schema, **kwargs):
        self.kwargs = kwargs
        return self

    def invoke(self, prompt):
        self.prompts.append(prompt)
        return self.salida


@pytest.mark.parametrize("salida", ["texto libre", {"puntaje": 5, "paso": True, "motivo": "x"}, None, {}])
def test_juzgar_salida_invalida_usa_fallback(monkeypatch, salida):
    monkeypatch.setattr(agents_base, "get_structured_model", ModeloFijo(salida))
    j = juez.juzgar("p", "r", "ref")
    assert j.puntaje == 0 and j.paso is False and j.motivo == "juez sin salida"


def test_juzgar_salida_valida_y_prompt(monkeypatch):
    m = ModeloFijo({"puntaje": 0.75, "paso": True, "motivo": "ok"})
    monkeypatch.setattr(agents_base, "get_structured_model", m)
    monkeypatch.setattr(juez, "JUEZ_MODEL", "juez-x")
    j = juez.juzgar("PET", "RESP", "REF")
    assert (j.puntaje, j.paso) == (0.75, True)
    assert m.kwargs["model"] == "juez-x"
    assert "PET" in m.prompts[0] and "RESP" in m.prompts[0] and "REF" in m.prompts[0]


def test_consolidar_vacio_no_llama_al_llm(monkeypatch):
    def _no(*a, **k):
        raise AssertionError("no debía llamar al LLM")

    monkeypatch.setattr(agents_base, "get_structured_model", _no)
    assert juez.consolidar_reglas([]) == []


def test_consolidar_salida_invalida_devuelve_candidatas_truncadas(monkeypatch):
    monkeypatch.setattr(agents_base, "get_structured_model", ModeloFijo("basura"))
    candidatas = [f"r{i}" for i in range(12)]
    assert juez.consolidar_reglas(candidatas) == candidatas[: juez.MAX_REGLAS]
    assert juez.MAX_REGLAS == 8


def test_consolidar_trunca_salida_valida(monkeypatch):
    monkeypatch.setattr(agents_base, "get_structured_model", ModeloFijo(juez.Manual(reglas=[f"m{i}" for i in range(11)])))
    assert juez.consolidar_reglas(["a"]) == [f"m{i}" for i in range(8)]


# --- scripts/entrenar_reglas.entrenar() de punta a punta -----------------------


@pytest.fixture
def entrenar_mod():
    return importlib.import_module("scripts.entrenar_reglas")


def test_entrenar_guarda_manual_v1_sin_archivar(montar, monkeypatch, tmp_path, entrenar_mod):
    items = [i for i in corrida.cargar_conjunto("entrenamiento") if i["agente_esperado"] == "exam_generator"][:2]
    assert len(items) == 2
    # Item 1: rechazo del rubric + aprobado en el intento 2. Item 2: aprobado a la primera.
    f = Falsos(
        examenes=[_examen(1), _examen(2), _examen(3)],
        veredictos=[_rechazo("R1"), VeredictoValidacion(aprobado=True), VeredictoValidacion(aprobado=True)],
    )
    # Las constraints falsas piden 2 preguntas/10 puntos, como los exámenes falsos
    app = montar(f, user_id=None)
    monkeypatch.setattr(entrenar_mod, "construir_grafo", lambda **k: app)
    monkeypatch.setattr(entrenar_mod, "user_id_por_email", lambda email: 42)

    juicios = iter([juez.Juicio(puntaje=0.2, paso=False, motivo="Falta seguridad"),
                    juez.Juicio(puntaje=1, paso=True, motivo="ok")])
    juzgados = []

    def _juzgar(pet, resp, ref):
        juzgados.append((pet, resp, ref))
        return next(juicios)

    monkeypatch.setattr(entrenar_mod, "juzgar", _juzgar)

    reflector_prompts = []

    class Reflector:
        def invoke(self, prompt):
            reflector_prompts.append(prompt)
            return Reflexion(diagnostico="d", plan="p", regla_general="Incluye una pregunta de seguridad.")

    # El reflector pasa por base.invocar_estructurado -> base.get_structured_model
    monkeypatch.setattr(agents_base, "get_structured_model", lambda *a, **k: Reflector())
    consolidadas = []

    def _consolidar(cands):
        consolidadas.append(list(cands))
        return sorted(set(cands))

    monkeypatch.setattr(entrenar_mod, "consolidar_reglas", _consolidar)
    ruta = tmp_path / "reglas.json"
    monkeypatch.setattr(manual_reglas, "RUTA_REGLAS", ruta)
    monkeypatch.setattr(manual_reglas, "get_selection", lambda: SimpleNamespace(llm_model="m-test"))

    entrenar_mod.entrenar("demo@x", limite=2)

    datos = json.loads(ruta.read_text(encoding="utf-8"))["exam_generator"]
    assert datos["version"] == 1 and datos["modelo"] == "m-test"
    assert datos["preguntas"] == [i["id"] for i in items]
    assert datos["oraculo_pass"] == "1/2"
    # Candidatas: regla de la reflexión dentro del grafo (item 1) + la del reflector (oráculo FAIL)
    assert datos["candidatas"] == ["Consulta siempre las rúbricas.", "Incluye una pregunta de seguridad."]
    assert datos["reglas"] == sorted(datos["candidatas"])
    assert consolidadas == [datos["candidatas"]]  # manual vigente vacío + candidatas
    assert len(reflector_prompts) == 1 and "Falta seguridad" in reflector_prompts[0]
    # El oráculo juzga la respuesta que iría al HITL, con la referencia
    assert juzgados[0] == (items[0]["peticion"], "BORRADOR_INTENTO_2", items[0]["referencia"])
    # Entrenar nunca reanuda el HITL: no hay casos archivados
    assert f.archivados == []
    assert {uid for uid, _ in f.recordados} == {42}


def test_entrenar_parte_del_manual_vigente(montar, monkeypatch, tmp_path, entrenar_mod):
    f = Falsos(examenes=[_examen(1)], veredictos=[VeredictoValidacion(aprobado=True)])
    app = montar(f, user_id=None)
    monkeypatch.setattr(entrenar_mod, "construir_grafo", lambda **k: app)
    monkeypatch.setattr(entrenar_mod, "user_id_por_email", lambda email: 42)
    monkeypatch.setattr(entrenar_mod, "juzgar", lambda *a: juez.Juicio(puntaje=1, paso=True, motivo="ok"))
    recibidas = []
    monkeypatch.setattr(entrenar_mod, "consolidar_reglas", lambda c: recibidas.append(list(c)) or c)
    monkeypatch.setattr(manual_reglas, "RUTA_REGLAS", tmp_path / "reglas.json")
    monkeypatch.setattr(manual_reglas, "get_selection", lambda: SimpleNamespace(llm_model="m-test"))
    manual_reglas.guardar("exam_generator", ["VIGENTE"])

    entrenar_mod.entrenar("demo@x", limite=1)
    assert recibidas == [["VIGENTE"]]
    assert json.loads((tmp_path / "reglas.json").read_text(encoding="utf-8"))["exam_generator"]["version"] == 2


@pytest.mark.parametrize("error", [ConnectionError("sin red"), ValueError("ValidationError de Juicio")])
def test_juez_y_consolidar_toleran_excepciones_del_modelo(monkeypatch, error):
    class Lanza:
        def invoke(self, prompt):
            raise error

    monkeypatch.setattr(agents_base, "get_structured_model", lambda *a, **k: Lanza())
    j = juez.juzgar("p", "r", "ref")
    assert (j.puntaje, j.paso, j.motivo) == (0, False, "juez sin salida")
    cands = [f"r{i}" for i in range(10)]
    assert juez.consolidar_reglas(cands) == cands[: juez.MAX_REGLAS]


# --- scripts/evaluar.calibrar_juez ---------------------------------------------


def test_calibrar_juez_clasifica_veredictos_renderizados(monkeypatch, capsys):
    from src.agents.schemas import render_veredicto

    evaluar_mod = importlib.import_module("scripts.evaluar")
    filas = [
        (render_veredicto(VeredictoValidacion(aprobado=True, etapa="llm")), "aprobado"),
        (render_veredicto(VeredictoValidacion(aprobado=True, etapa="determinista")), "aprobado"),
        (render_veredicto(VeredictoValidacion(aprobado=False, etapa="determinista", motivos=["x"])), "rechazado"),
        (render_veredicto(VeredictoValidacion(aprobado=False, etapa="llm", motivos=["x"])), "aprobado"),
        ("texto legado sin cabecera", "rechazado"),
        ("veredicto: aprobado (legado en minúsculas)", "aprobado"),
    ]
    aprobaciones = [SimpleNamespace(veredicto=v, decision=d) for v, d in filas]

    class Q:
        def filter(self, *a, **k):
            return self

        def all(self):
            return aprobaciones

    monkeypatch.setattr(evaluar_mod, "SessionLocal", lambda: SimpleNamespace(query=lambda *a: Q(), close=lambda: None))
    evaluar_mod.calibrar_juez()
    salida = capsys.readouterr().out
    # Los veredictos deterministas ("revisión automática") se excluyen: no son del juez LLM
    assert "{'aciertos': 3, 'falsos_pass': 0, 'falsos_fail': 1, 'total': 4}" in salida


def test_cabecera_aprobado_no_aparece_en_rechazos():
    from src.agents.schemas import render_veredicto

    for etapa in ("llm", "determinista"):
        texto = render_veredicto(VeredictoValidacion(aprobado=False, etapa=etapa)).upper()
        assert "VEREDICTO: APROBADO" not in texto


def _entrenar_basico(montar, monkeypatch, tmp_path, entrenar_mod, falsos, correr=None, juicio_paso=True):
    app = montar(falsos, user_id=None)
    monkeypatch.setattr(entrenar_mod, "construir_grafo", lambda **k: app)
    monkeypatch.setattr(entrenar_mod, "user_id_por_email", lambda email: 42)
    monkeypatch.setattr(entrenar_mod, "juzgar", lambda *a: juez.Juicio(puntaje=1, paso=juicio_paso, motivo="m"))
    monkeypatch.setattr(entrenar_mod, "consolidar_reglas", lambda c: list(c))
    if correr is not None:
        monkeypatch.setattr(entrenar_mod, "correr", correr)
    ruta = tmp_path / "reglas.json"
    monkeypatch.setattr(manual_reglas, "RUTA_REGLAS", ruta)
    monkeypatch.setattr(manual_reglas, "get_selection", lambda: SimpleNamespace(llm_model="m-test"))
    return ruta


def test_entrenar_sin_candidatas_no_toca_el_manual(montar, monkeypatch, tmp_path, entrenar_mod):
    f = Falsos(examenes=[_examen(1)], veredictos=[VeredictoValidacion(aprobado=True)])
    ruta = _entrenar_basico(montar, monkeypatch, tmp_path, entrenar_mod, f)
    entrenar_mod.entrenar("demo@x", limite=1)
    assert not ruta.exists()


def test_entrenar_sigue_si_un_item_falla(montar, monkeypatch, tmp_path, entrenar_mod):
    llamadas = []

    def _correr(app, item, user_id):
        llamadas.append(item["id"])
        if len(llamadas) == 1:
            raise TimeoutError("timeout")
        return {"respuesta": "R", "reglas_nuevas": ["REGLA_DEL_2"]}

    f = Falsos(examenes=[], veredictos=[])
    ruta = _entrenar_basico(montar, monkeypatch, tmp_path, entrenar_mod, f, correr=_correr)
    entrenar_mod.entrenar("demo@x", limite=2)
    assert len(llamadas) == 2
    datos = json.loads(ruta.read_text(encoding="utf-8"))["exam_generator"]
    assert datos["reglas"] == ["REGLA_DEL_2"]
    assert datos["oraculo_pass"] == "1/1"  # el item fallido no se juzgó: no cuenta
    assert datos["preguntas"] == [llamadas[1]]


# --- scripts/evaluar.evaluar() con fakes ---------------------------------------


def test_evaluar_registra_fila_de_error_y_sigue(monkeypatch, tmp_path):
    evaluar_mod = importlib.import_module("scripts.evaluar")
    items = corrida.cargar_conjunto("prueba")[:3]
    llamadas = []

    def _correr(app, item, user_id):
        llamadas.append(item["id"])
        if len(llamadas) == 2:
            raise TimeoutError("timeout del LLM")
        return {"id": item["id"], "agente": item["agente_esperado"], "respuesta": "R",
                "fuentes": [], "intentos": None, "errores_reglas": None, "aprobado_rubric": None,
                "reglas_nuevas": [], "tokens": 10, "segundos": 1.0}

    monkeypatch.setattr(evaluar_mod, "user_id_por_email", lambda e: 1)
    monkeypatch.setattr(evaluar_mod, "describe_llm", lambda: {"llm_model": "m"})
    monkeypatch.setattr(evaluar_mod, "construir_grafo", lambda **k: object())
    monkeypatch.setattr(evaluar_mod, "correr", _correr)
    monkeypatch.setattr(evaluar_mod, "juzgar", lambda *a: juez.Juicio(puntaje=0.5, paso=True, motivo="m"))
    monkeypatch.setattr(evaluar_mod, "DIR_METRICS", tmp_path)
    monkeypatch.setattr(evaluar_mod, "JUEZ_MODEL", "juez-x")

    evaluar_mod.evaluar("prueba", "demo@x", limite=3)
    assert llamadas == [i["id"] for i in items]
    (ruta,) = tmp_path.glob("eval_prueba_*.json")
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    filas, resumen = datos["filas"], datos["resumen"]
    assert filas[1] == {"id": items[1]["id"], "tipo": items[1]["tipo"], "error": "timeout del LLM"}
    assert resumen["n"] == 3 and resumen["errores"] == 1
    assert resumen["juez_puntaje"] == 0.5 and resumen["agente_ok"] == 1.0  # la fila de error no cuenta
    assert resumen["intentos"] is None and resumen["tokens"] == 10.0


def test_evaluar_no_acepta_conjunto_de_entrenamiento():
    import os
    import subprocess
    import sys
    from pathlib import Path

    raiz = Path(__file__).resolve().parents[1]
    p = subprocess.run(
        [sys.executable, "scripts/evaluar.py", "--conjunto", "entrenamiento"],
        cwd=raiz, capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(raiz)}, timeout=120,
    )
    assert p.returncode == 2 and "invalid choice" in p.stderr
