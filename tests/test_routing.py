"""Enrutado determinista por reglas (verbo imperativo al inicio + objeto cercano)."""

import pytest

from src.orchestrator.routing import REGLAS_ROUTER, enrutar_por_reglas


@pytest.mark.parametrize(
    "peticion, agente",
    [
        ("Genera un examen de 6 preguntas sobre la ley de Ohm", "exam_generator"),
        ("GENERA UN EXAMEN de electricidad", "exam_generator"),
        ("  genera un examen", "exam_generator"),
        ("Por favor, genera un examen de Ohm", "exam_generator"),
        ("Diseña una prueba escrita de mecanismos", "exam_generator"),
        ("Prepara dos exámenes de recuperación", "exam_generator"),
        ("Genera un examen de la unidad 3", "exam_generator"),  # "unidad" queda lejos del verbo
        ("Crea una rúbrica de evaluación para el proyecto", "rubric"),
        ("Elabora una rubrica para la exposición", "rubric"),
        ("Redacta los criterios de calificación del trimestre", "rubric"),
        ("Hazme una rúbrica para el examen", "rubric"),
        ("Crea los criterios de evaluación de la unidad 2", "rubric"),
        ("Estructura la unidad 3 en 8 sesiones", "curriculum"),
        ("Organiza el temario de electricidad", "curriculum"),
        ("Planifica las sesiones del trimestre", "curriculum"),
    ],
)
def test_regla_unica_enruta(peticion, agente):
    assert enrutar_por_reglas(peticion) == agente


@pytest.mark.parametrize("peticion", ["Crea examen y rúbrica", "Genera rúbrica y examen"])
def test_varias_reglas_es_ambigua(peticion):
    coinciden = [a for a, p in REGLAS_ROUTER.items() if p.search(peticion)]
    assert len(coinciden) >= 2
    assert enrutar_por_reglas(peticion) is None


@pytest.mark.parametrize(
    "peticion",
    [
        # Preguntas de tutor / alumno
        "¿Qué es un circuito en serie?",
        "Explica la ley de Ohm con los apuntes",
        "¿Cómo organizo mi estudio para el control?",
        "No entiendo la pregunta 3 del examen",
        # Falsos positivos de la versión anterior (bug corregido)
        "¿Qué estructura tiene un examen?",
        "Ayúdame a preparar el examen de mañana",
        "¿Qué es la creatividad en una unidad didáctica?",
        "Crea un circuito con control de velocidad",
        "Genera 10 preguntas tipo test sobre la unidad 2",
        "Genera un ejercicio de programación en Python",
        "Haz un resumen del bloque 2",
        "Explica cómo se elabora un examen",
        # Sin verbo imperativo al inicio u objeto demasiado lejos
        "Diseño de una prueba escrita",
        "Hola, genera un examen",
        "Hazme un control de electricidad",
        "Elabora la programación del trimestre",
        "Examen",
        "",
    ],
)
def test_no_enrutan_por_regla(peticion):
    assert enrutar_por_reglas(peticion) is None
