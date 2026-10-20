"""Enrutado determinista del docente (regla primero, LLM después).

Lección del notebook (§5D): un campo ambiguo del enrutador LLM apagó una rama
entera. Aquí una petición se enruta sin LLM solo si UNA regla la cubre: empieza
con un verbo en imperativo y el objeto está a 3 palabras como máximo
("Genera un examen…"). Si ninguna o varias coinciden, decide `DecisionRouter`.
"""

import re

_VERBO = r"(genera|crea|elabora|diseña|disena|prepara|redacta|haz|hazme|propón|propon|estructura|organiza|planifica|distribuye)"

_OBJETOS = {
    "exam_generator": r"(examen|exámenes|prueba escrita)",
    "rubric": r"(rúbrica|rubrica|criterios de (evaluación|calificación|corrección))",
    "curriculum": r"(unidad|sesiones|temario)",
}

REGLAS_ROUTER = {
    agente: re.compile(rf"^\s*(por favor,?\s+)?{_VERBO}\s+(\S+\s+){{0,3}}{objeto}\b", re.IGNORECASE)
    for agente, objeto in _OBJETOS.items()
}


def enrutar_por_reglas(peticion: str) -> str | None:
    coinciden = [a for a, patron in REGLAS_ROUTER.items() if patron.search(peticion)]
    return coinciden[0] if len(coinciden) == 1 else None
