"""Juez LLM fuera del sistema (notebook §5) y consolidación del manual (§5B.6).

`juzgar` compara la respuesta con la referencia. Es el oráculo del entrenamiento
y el juez de la evaluación: nunca se usa dentro del grafo, porque el sistema no
debe ver la referencia. Usa JUEZ_MODEL (idealmente distinto del generador).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.agents.base import invocar_estructurado
from src.config import EVAL_MODEL, JUEZ_MODEL

MAX_REGLAS = 8


class Juicio(BaseModel):
    puntaje: float = Field(ge=0, le=1, description="Fracción de los criterios de la referencia que cumple")
    paso: bool = Field(description="True si cumple lo esencial de la referencia sin contradecirla")
    motivo: str = Field(description="Una oración: qué falta o qué sobra")


class Manual(BaseModel):
    reglas: list[str] = Field(default_factory=list)


def juzgar(peticion: str, respuesta: str, referencia: str) -> Juicio:
    return invocar_estructurado(
        Juicio,
        "Evalúas la respuesta de un asistente docente contra una referencia.\n\n"
        f"PETICIÓN:\n{peticion}\n\nREFERENCIA (criterios que debe cumplir):\n{referencia}\n\n"
        f"RESPUESTA:\n{respuesta}\n\n"
        "puntaje = fracción de los criterios de la referencia que la respuesta cumple. "
        "paso = true si cumple lo esencial y no afirma nada que contradiga la referencia. "
        "No penalices información extra correcta ni el estilo.",
        JUEZ_MODEL,
        Juicio(puntaje=0, paso=False, motivo="juez sin salida"),
    )


def consolidar_reglas(candidatas: list[str]) -> list[str]:
    """Fusiona reglas candidatas en un manual de <= MAX_REGLAS (EVAL_MODEL)."""
    if not candidatas:
        return []
    manual = invocar_estructurado(
        Manual,
        "Estas son reglas candidatas que un generador de exámenes escribió tras fallar "
        "peticiones de entrenamiento:\n" + "\n".join(f"- {r}" for r in candidatas) + "\n\n"
        f"Fusiónalas en un manual de máximo {MAX_REGLAS} reglas generales, accionables y sin "
        "contradicciones. Prioriza las que se repiten y descarta las específicas de una sola petición.",
        EVAL_MODEL,
        Manual(reglas=candidatas),
    )
    return manual.reglas[:MAX_REGLAS]
