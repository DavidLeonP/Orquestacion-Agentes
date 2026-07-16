"""Pruebas unitarias de contratos Pydantic compartidos entre agentes."""

from src.agents.schemas import (
    ExamenGenerado,
    VeredictoValidacion,
    dump_state,
    load_state,
    render_veredicto,
    safe_parse,
)


def test_veredicto_roundtrip_dict():
    v = VeredictoValidacion(
        aprobado=True,
        motivos=[],
        criterios_evaluados=["puntuacion"],
        resumen="OK",
    )
    data = dump_state(v)
    loaded = load_state(VeredictoValidacion, data)
    assert loaded.aprobado is True
    assert loaded.resumen == "OK"


def test_safe_parse_veredicto_malformado_no_rompe():
    modelo, ok = safe_parse(VeredictoValidacion, {"foo": "bar"})
    assert ok is False
    assert modelo.aprobado is False
    assert "salida_no_estructurada" in modelo.motivos or modelo.motivos


def test_safe_parse_veredicto_texto_legado():
    modelo, ok = safe_parse(
        VeredictoValidacion,
        "VEREDICTO: APROBADO\nTodo correcto",
    )
    assert ok is True
    assert modelo.aprobado is True


def test_safe_parse_examen_desde_texto():
    modelo, ok = safe_parse(ExamenGenerado, "Examen de prueba sin estructura")
    assert ok is False
    assert "Examen de prueba" in modelo.texto_completo


def test_routing_usa_bool_no_substring():
    """El orquestador debe decidir por .aprobado tipado."""
    rechazado = VeredictoValidacion(aprobado=False, motivos=["falta seguridad"])
    aprobado = VeredictoValidacion(aprobado=True, motivos=[])
    assert rechazado.aprobado is False
    assert aprobado.aprobado is True
    assert "VEREDICTO" not in dump_state(rechazado)


def test_render_veredicto_legible():
    texto = render_veredicto(
        VeredictoValidacion(
            aprobado=False,
            motivos=["Falta pregunta de seguridad"],
            resumen="Requiere cambios",
        )
    )
    assert "CAMBIOS REQUERIDOS" in texto
    assert "seguridad" in texto
