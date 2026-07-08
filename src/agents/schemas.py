"""Schemas Pydantic: constraints de examen y veredictos de validación."""

from typing import Literal

from pydantic import BaseModel, Field


class ConstraintsExamen(BaseModel):
    """Restricciones que debe cumplir un examen generado."""

    asignatura: str
    curso: str
    temas: list[str] = Field(description="Temas o unidades a cubrir")
    num_preguntas: int = Field(default=6, ge=1, le=20)
    duracion_minutos: int = Field(default=55, ge=10, le=180)
    dificultad: Literal["baja", "media", "alta"] = "media"
    puntuacion_total: float = Field(default=10.0)


class VeredictoValidacion(BaseModel):
    """Resultado de la validación cruzada del Rubric Agent."""

    aprobado: bool
    motivos: list[str] = Field(
        default_factory=list,
        description="Criterios de la rúbrica incumplidos o mejoras requeridas",
    )


class DecisionRouter(BaseModel):
    """Clasificación de intención del orquestador."""

    agente: Literal["curriculum", "exam_generator", "rubric", "tutor"] = Field(
        description=(
            "curriculum: estructurar contenidos/programaciones. "
            "exam_generator: crear examenes o pruebas. "
            "rubric: crear o aplicar criterios de evaluacion. "
            "tutor: dudas y explicaciones para alumnado."
        )
    )
