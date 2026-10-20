"""Pruebas de las decisiones puras de Reflexion (sin LLM ni BD)."""

import pytest

from src.agents.schemas import (
    ConstraintsExamen,
    ExamenGenerado,
    PreguntaExamen,
    Reflexion,
    VeredictoValidacion,
    dump_state,
    render_veredicto,
)
from src.orchestrator.reflexion import (
    MAX_INTENTOS,
    leccion,
    mejor_intento,
    peticion_examen,
    siguiente_paso,
    verificar_examen,
)

CONSTRAINTS = ConstraintsExamen(num_preguntas=2, puntuacion_total=10)


def _examen(*puntos, fuentes=("apuntes.txt",), solucion="x"):
    preguntas = [
        PreguntaExamen(numero=i, enunciado=f"P{i}", puntuacion=p, solucion=solucion)
        for i, p in enumerate(puntos, 1)
    ]
    return ExamenGenerado(preguntas=preguntas, fuentes=list(fuentes))


def _intento(aprobado, errores=(), nombre=""):
    return {
        "borrador": nombre,
        "errores": list(errores),
        "veredicto": dump_state(VeredictoValidacion(aprobado=aprobado)),
    }


def test_examen_valido_no_tiene_errores():
    assert verificar_examen(_examen(5, 5), CONSTRAINTS) == []


def test_detecta_incumplimientos_sin_llm():
    errores = verificar_examen(_examen(4, 4, 4, fuentes=(), solucion=""), CONSTRAINTS)
    texto = " ".join(errores)
    assert "3 preguntas" in texto
    assert "suman 12" in texto
    assert "soluciones" in texto
    assert "fuentes" in texto


def test_examen_sin_estructura_falla():
    assert verificar_examen(ExamenGenerado(), CONSTRAINTS) == [
        "El examen no tiene preguntas estructuradas."
    ]


def test_solucionario_global_cubre_soluciones():
    examen = _examen(5, 5, solucion="")
    examen.solucionario = "1) a 2) b"
    assert verificar_examen(examen, CONSTRAINTS) == []


def test_peticion_lleva_lecciones_y_no_borradores():
    texto = peticion_examen("Genera examen", CONSTRAINTS, ["Intento 1: faltó seguridad."])
    assert "faltó seguridad" in texto
    assert '"num_preguntas": 2' in texto
    assert "Borrador anterior" not in texto
    assert "lecciones" not in peticion_examen("Genera examen", CONSTRAINTS, [])


def test_siguiente_paso():
    assert siguiente_paso([_intento(True)]) == "aprobacion_docente"
    assert siguiente_paso([_intento(False)]) == "reflexionar"
    assert siguiente_paso([_intento(False)] * MAX_INTENTOS) == "aprobacion_docente"


def test_mejor_intento_no_entrega_el_ultimo_si_empeoro():
    # Intento 1 rechazado por el LLM; intento 2 rompe constraints: va el 1
    intentos = [_intento(False, nombre="i1"), _intento(False, ["suma"], nombre="i2")]
    assert mejor_intento(intentos)["borrador"] == "i1"


def test_mejor_intento_prefiere_aprobado():
    intentos = [_intento(False, ["suma"], nombre="i1"), _intento(True, nombre="i2")]
    assert mejor_intento(intentos)["borrador"] == "i2"


def test_leccion_y_veredicto_determinista():
    assert leccion(1, Reflexion(diagnostico="D.", plan="P.")) == "Intento 1: D. Plan: P."
    texto = render_veredicto(VeredictoValidacion(aprobado=False, etapa="determinista"))
    assert "revisión automática" in texto


# --- Fuentes citadas frente a fuentes vistas por las tools --------------------


def test_fuentes_vistas_none_no_comprueba_citas():
    assert verificar_examen(_examen(5, 5, fuentes=("cualquiera.pdf",)), CONSTRAINTS, None) == []


def test_cita_consultada_pasa_y_admite_prefijo():
    vistas = ["apuntes.txt", "rubrica_tecno.md"]
    assert verificar_examen(_examen(5, 5, fuentes=("Apuntes: apuntes.txt",)), CONSTRAINTS, vistas) == []
    assert verificar_examen(_examen(5, 5, fuentes=("rubrica_tecno.md",)), CONSTRAINTS, vistas) == []


def test_cita_inventada_falla_y_la_nombra():
    errores = verificar_examen(
        _examen(5, 5, fuentes=("apuntes.txt", "inventado.pdf")), CONSTRAINTS, ["apuntes.txt"]
    )
    assert len(errores) == 1
    assert "inventado.pdf" in errores[0] and "apuntes.txt" not in errores[0]


def test_vistas_vacias_da_error_especifico():
    errores = verificar_examen(_examen(5, 5, fuentes=("apuntes.txt",)), CONSTRAINTS, [])
    assert errores == ["No consultó ninguna fuente con las herramientas."]


def test_cita_sin_extension_se_acepta_por_subcadena():
    # "apuntes_electricidad" está contenido en "apuntes_electricidad.md" -> f in v
    assert verificar_examen(
        _examen(5, 5, fuentes=("apuntes_electricidad",)), CONSTRAINTS, ["apuntes_electricidad.md"]
    ) == []


def test_citas_vacias_se_descartan():
    assert verificar_examen(_examen(5, 5, fuentes=("", "  ")), CONSTRAINTS, ["apuntes.txt"]) == [
        "No cita las fuentes consultadas."
    ]
    assert verificar_examen(_examen(5, 5, fuentes=("", "apuntes.txt")), CONSTRAINTS, ["apuntes.txt"]) == []


def test_cita_compara_por_stem_sin_mayusculas():
    vistas = ["docs/Apuntes_Electricidad.MD"]
    assert verificar_examen(_examen(5, 5, fuentes=("apuntes_electricidad",)), CONSTRAINTS, vistas) == []
    assert verificar_examen(_examen(5, 5, fuentes=("APUNTES_ELECTRICIDAD.pdf",)), CONSTRAINTS, vistas) == []
    assert verificar_examen(_examen(5, 5, fuentes=("Txt",)), CONSTRAINTS, ["apuntes.txt"]) != []


def test_stem_corto_no_valida_cita_inventada_que_lo_contiene():
    # El stem se compara como palabra completa, no como subcadena
    assert verificar_examen(_examen(5, 5, fuentes=("apuntes_inventados.pdf",)), CONSTRAINTS, ["apuntes.txt"]) != []
    assert verificar_examen(_examen(5, 5, fuentes=("libro2021.pdf",)), CONSTRAINTS, ["1.pdf"]) != []


def test_peticion_lleva_reglas_y_casos():
    texto = peticion_examen("Genera", CONSTRAINTS, [], reglas=["R1"], casos=["C1"])
    assert "Reglas aprendidas" in texto and "- R1" in texto
    assert "Exámenes aprobados parecidos" in texto and "- C1" in texto
    assert "Intentos anteriores" not in texto
    vacio = peticion_examen("Genera", CONSTRAINTS, [])
    assert "Reglas aprendidas" not in vacio and "aprobados parecidos" not in vacio


def test_prompt_reflexion_incluye_borrador_motivos_y_previas():
    from src.orchestrator.reflexion import prompt_reflexion

    texto = prompt_reflexion("PET", "BORR", ["M1", "M2"], [])
    assert "PET" in texto and "BORR" in texto and "- M1" in texto and "(ninguna)" in texto
    assert "L0" in prompt_reflexion("PET", "BORR", ["M1"], ["L0"])


# --- mejor_intento: desempates ------------------------------------------------


def test_mejor_intento_empate_elige_el_primero():
    intentos = [_intento(False, ["a"], nombre="i1"), _intento(False, ["b"], nombre="i2")]
    assert mejor_intento(intentos)["borrador"] == "i1"
    dos_aprobados = [_intento(True, nombre="i1"), _intento(True, nombre="i2")]
    assert mejor_intento(dos_aprobados)["borrador"] == "i1"


def test_mejor_intento_rechazo_llm_gana_a_determinista():
    intentos = [_intento(False, ["suma", "fuentes"], nombre="det"), _intento(False, nombre="llm")]
    assert mejor_intento(intentos)["borrador"] == "llm"


def test_mejor_intento_menos_errores_deterministas():
    intentos = [_intento(False, ["a", "b"], nombre="i1"), _intento(False, ["a"], nombre="i2")]
    assert mejor_intento(intentos)["borrador"] == "i2"


# --- Ronda 4: criterios de la rúbrica ------------------------------------------

from src.agents.schemas import CriteriosRubrica  # noqa: E402
from src.orchestrator.reflexion import (  # noqa: E402
    CITAS_INVENTADAS,
    PREFIJOS_REGENERAR,
    SIN_CITAS,
    SIN_CONSULTAS,
    SIN_PREGUNTAS,
    _verificar_criterios,
    modo_reintento,
)


def _ex_tipos(*pares):
    """pares: (tipo, puntuacion) o (tipo, puntuacion, con_calculo)."""
    return ExamenGenerado(
        preguntas=[PreguntaExamen(numero=i, enunciado="e", puntuacion=par[1], tipo=par[0], solucion="s",
                                  con_calculo=par[2] if len(par) > 2 else False)
                   for i, par in enumerate(pares, 1)],
        fuentes=["apuntes.txt"],
    )


def test_criterios_por_defecto_no_exigen_nada():
    assert _verificar_criterios(_ex_tipos(("otro", 5), ("otro", 5)), CriteriosRubrica()) == []


def test_criterio_seguridad():
    c = CriteriosRubrica(requiere_seguridad=True)
    (e,) = _verificar_criterios(_ex_tipos(("numerico", 5), ("definicion", 5)), c)
    assert "seguridad" in e
    assert _verificar_criterios(_ex_tipos(("numerico", 5), ("seguridad", 5)), c) == []


def test_criterio_pct_numerico_y_borde_exacto():
    c = CriteriosRubrica(pct_min_numerico=0.4)
    assert _verificar_criterios(_ex_tipos(("numerico", 4), ("definicion", 6)), c) == []  # 40% exacto
    (e,) = _verificar_criterios(_ex_tipos(("numerico", 3.9), ("definicion", 6.1)), c)
    assert "39%" in e and "40%" in e
    # Se mide por puntuación, no por número de preguntas
    assert _verificar_criterios(_ex_tipos(("numerico", 6), ("definicion", 2), ("definicion", 2)), c) == []
    # Flotantes que no suman exacto: 1/3 + 1/3 de 1 → 0.666... >= 2/3
    c2 = CriteriosRubrica(pct_min_numerico=2 / 3)
    assert _verificar_criterios(_ex_tipos(("numerico", 1 / 3), ("numerico", 1 / 3), ("otro", 1 / 3)), c2) == []


def test_criterio_pct_con_total_cero():
    # Sin preguntas el total es 0: no divide por cero y el porcentaje cuenta como 0
    c = CriteriosRubrica(pct_min_numerico=0.4)
    (e,) = _verificar_criterios(ExamenGenerado(), c)
    assert "0%" in e
    assert _verificar_criterios(ExamenGenerado(), CriteriosRubrica()) == []


def test_criterio_tipos_minimos_sin_contar_otro():
    c = CriteriosRubrica(tipos_minimos=3)
    assert _verificar_criterios(_ex_tipos(("numerico", 3), ("definicion", 3), ("esquema", 4)), c) == []
    (e,) = _verificar_criterios(_ex_tipos(("numerico", 3), ("definicion", 3), ("otro", 4)), c)
    assert "Hay 2 tipos" in e
    (e,) = _verificar_criterios(_ex_tipos(("otro", 5), ("otro", 5)), CriteriosRubrica(tipos_minimos=1))
    assert "Hay 0 tipos" in e


def test_criterios_varios_errores_a_la_vez():
    c = CriteriosRubrica(requiere_seguridad=True, pct_min_numerico=0.5, tipos_minimos=2)
    assert len(_verificar_criterios(_ex_tipos(("otro", 10)), c)) == 3


def test_verificar_examen_aplica_criterios_solo_si_se_pasan():
    ex = _ex_tipos(("otro", 5), ("otro", 5))
    c = CriteriosRubrica(requiere_seguridad=True)
    assert verificar_examen(ex, CONSTRAINTS, None) == []
    assert verificar_examen(ex, CONSTRAINTS, None, c) != []
    # Sin preguntas: solo el error estructural, sin criterios
    assert verificar_examen(ExamenGenerado(), CONSTRAINTS, None, c) == [SIN_PREGUNTAS]


# --- modo_reintento ---------------------------------------------------------------


def _int(errores, preguntas=True):
    return {"examen": {"preguntas": [{"numero": 1}] if preguntas else []}, "errores": errores}


@pytest.mark.parametrize(
    "errores, preguntas, modo",
    [
        ([], True, "reparar"),  # rechazo del Rubric Agent
        (["Tiene 3 preguntas y se pidieron 2."], True, "reparar"),
        (["La rúbrica exige una pregunta de seguridad y no hay ninguna."], True, "reparar"),
        ([SIN_PREGUNTAS], False, "regenerar"),
        ([], False, "regenerar"),
        ([SIN_CITAS], True, "regenerar"),
        ([SIN_CONSULTAS], True, "regenerar"),
        (["Las puntuaciones suman 9", f"{CITAS_INVENTADAS}: ['x']."], True, "regenerar"),
    ],
)
def test_modo_reintento(errores, preguntas, modo):
    assert modo_reintento(_int(errores, preguntas)) == modo


def test_prefijos_regenerar_coinciden_con_los_mensajes_reales():
    # Si alguien cambia un mensaje de verificar_examen, modo_reintento dejaría de verlo
    sin_fuentes = verificar_examen(_examen(5, 5, fuentes=()), CONSTRAINTS)
    no_consulto = verificar_examen(_examen(5, 5), CONSTRAINTS, [])
    inventada = verificar_examen(_examen(5, 5, fuentes=("x.pdf",)), CONSTRAINTS, ["a.txt"])
    for errores in (sin_fuentes, no_consulto, inventada, [SIN_PREGUNTAS]):
        assert errores and errores[0].startswith(PREFIJOS_REGENERAR), errores


def test_peticion_examen_reparar_lleva_motivos_y_borrador():
    intento = {"borrador": "BORRADOR_X", "veredicto": {"motivos": ["M1", "M2"], "resumen": "R"}}
    texto = peticion_examen("Genera", CONSTRAINTS, ["L1"], reparar=intento)
    assert "CORRIGE este borrador" in texto and "- M1" in texto and "- M2" in texto
    assert texto.rstrip().endswith("BORRADOR:\nBORRADOR_X")
    assert "- L1" in texto
    # Sin motivos usa el resumen
    sin_motivos = {"borrador": "B", "veredicto": {"motivos": [], "resumen": "RESUMEN"}}
    assert "- RESUMEN" in peticion_examen("Genera", CONSTRAINTS, [], reparar=sin_motivos)
    assert "CORRIGE" not in peticion_examen("Genera", CONSTRAINTS, [], reparar=None)


# --- Falsos rechazos de los criterios (comportamiento actual, documentado) --------


def test_tipos_minimos_se_limita_al_numero_de_preguntas():
    # 3 tipos exigidos con 2 preguntas: el mínimo efectivo es 2 (antes era imposible)
    c = CriteriosRubrica(tipos_minimos=3)
    assert _verificar_criterios(_ex_tipos(("numerico", 5), ("definicion", 5)), c) == []
    (e,) = _verificar_criterios(_ex_tipos(("numerico", 5), ("numerico", 5)), c)
    assert "Hay 1 tipos" in e and "al menos 2" in e


def test_seguridad_con_calculo_suma_al_pct_numerico():
    c = CriteriosRubrica(pct_min_numerico=0.4, requiere_seguridad=True)
    assert _verificar_criterios(_ex_tipos(("numerico", 3), ("seguridad", 2, True), ("definicion", 5)), c) == []
    # Sin con_calculo no cuenta: 30% < 40%
    (e,) = _verificar_criterios(_ex_tipos(("numerico", 3), ("seguridad", 2), ("definicion", 5)), c)
    assert "30%" in e


def test_con_calculo_en_teoria_tambien_cuenta():
    c = CriteriosRubrica(pct_min_numerico=0.5)
    assert _verificar_criterios(_ex_tipos(("definicion", 5, True), ("definicion", 5)), c) == []


def test_mensaje_de_seguridad():
    (e,) = _verificar_criterios(_ex_tipos(("numerico", 10)), CriteriosRubrica(requiere_seguridad=True))
    assert e == "La rúbrica exige una pregunta de seguridad y no hay ninguna."


def test_peticion_solo_teoria_choca_con_pct_de_la_rubrica():
    # Comportamiento actual DOCUMENTADO: "3 preguntas de teoría" + rúbrica con 40%
    # numérico -> gana la rúbrica (rechazo determinista; las constraints no tienen
    # tipos). El docente ve el motivo en el HITL.
    c = CriteriosRubrica(pct_min_numerico=0.4)
    ex = _ex_tipos(("definicion", 4), ("definicion", 3), ("definicion", 3))
    assert verificar_examen(ex, ConstraintsExamen(num_preguntas=3, puntuacion_total=10), None, c)
