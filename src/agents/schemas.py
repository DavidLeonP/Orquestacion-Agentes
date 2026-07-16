"""Schemas Pydantic: contratos estables entre agentes y orquestador.

El LLM puede cambiar; estos modelos son la API interna tipada. El estado de
LangGraph guarda dicts (`model_dump`); los nodos leen con `load_state` /
`safe_parse` para que un mensaje mal formado no corrompa el routing.
"""

from __future__ import annotations

from typing import Any, Literal, TypeVar

from pydantic import BaseModel, Field, ValidationError

T = TypeVar("T", bound=BaseModel)


class ConstraintsExamen(BaseModel):
    """Restricciones que debe cumplir un examen generado."""

    asignatura: str = Field(default="Tecnología")
    curso: str = Field(default="3º ESO")
    temas: list[str] = Field(
        default_factory=lambda: ["electricidad"],
        description="Temas o unidades a cubrir",
    )
    num_preguntas: int = Field(default=6, ge=1, le=20)
    duracion_minutos: int = Field(default=55, ge=10, le=180)
    dificultad: Literal["baja", "media", "alta"] = "media"
    puntuacion_total: float = Field(default=10.0)


class PreguntaExamen(BaseModel):
    """Unidad de pregunta compartida Exam → Rubric / HITL."""

    numero: int = Field(ge=1)
    enunciado: str
    puntuacion: float = Field(gt=0)
    tipo: Literal["definicion", "numerico", "esquema", "tabla", "seguridad", "otro"] = "otro"
    solucion: str = ""


class ExamenGenerado(BaseModel):
    """Borrador estructurado del Exam Generator."""

    asignatura: str = "Tecnología"
    curso: str = "3º ESO"
    titulo: str = "Examen"
    duracion_minutos: int = Field(default=55, ge=10, le=180)
    puntuacion_total: float = Field(default=10.0)
    preguntas: list[PreguntaExamen] = Field(default_factory=list)
    solucionario: str = ""
    fuentes: list[str] = Field(default_factory=list)
    texto_completo: str = Field(
        default="",
        description="Vista legible (markdown/texto) para HITL y API",
    )


class VeredictoValidacion(BaseModel):
    """Resultado tipado de la validación cruzada (Rubric → Orquestador)."""

    aprobado: bool
    motivos: list[str] = Field(
        default_factory=list,
        description="Incumplimientos o mejoras requeridas",
    )
    criterios_evaluados: list[str] = Field(default_factory=list)
    resumen: str = ""


class PayloadAprobacion(BaseModel):
    """Payload estable del interrupt HITL."""

    mensaje: str = "Examen validado. ¿Apruebas el material? (si/no)"
    borrador: str
    veredicto: VeredictoValidacion
    examen: ExamenGenerado | None = None


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


def dump_state(model: BaseModel) -> dict[str, Any]:
    """Serializa un contrato para el estado LangGraph / JSON."""
    return model.model_dump(mode="json")


def load_state(cls: type[T], data: Any) -> T:
    """Carga un contrato desde el estado (dict u objeto ya tipado)."""
    if isinstance(data, cls):
        return data
    if data is None:
        raise ValueError(f"{cls.__name__}: data is None")
    if isinstance(data, BaseModel):
        return cls.model_validate(data.model_dump())
    if isinstance(data, str):
        # Compatibilidad legado: veredicto texto libre
        if cls is VeredictoValidacion:
            aprobado = "VEREDICTO: APROBADO" in data.upper()
            return cls(  # type: ignore[call-arg]
                aprobado=aprobado,
                motivos=[] if aprobado else [data[:500]],
                resumen=data[:500],
            )
        raise TypeError(f"No se puede cargar {cls.__name__} desde str")
    return cls.model_validate(data)


def safe_parse(
    cls: type[T],
    raw: Any,
    *,
    fallback: T | None = None,
) -> tuple[T, bool]:
    """Valida raw; si falla, usa fallback. Devuelve (modelo, ok)."""
    try:
        return load_state(cls, raw), True
    except (ValidationError, TypeError, ValueError):
        if fallback is not None:
            return fallback, False
        if cls is VeredictoValidacion:
            return (  # type: ignore[return-value]
                VeredictoValidacion(
                    aprobado=False,
                    motivos=["salida_no_estructurada"],
                    resumen="El modelo no devolvió un veredicto válido.",
                ),
                False,
            )
        if cls is ExamenGenerado:
            texto = raw if isinstance(raw, str) else str(raw)
            return (  # type: ignore[return-value]
                ExamenGenerado(texto_completo=texto, preguntas=[]),
                False,
            )
        if cls is ConstraintsExamen:
            return ConstraintsExamen(), False  # type: ignore[return-value]
        raise


def render_examen(examen: ExamenGenerado) -> str:
    """Vista legible del examen para HITL / API / regeneración."""
    if examen.texto_completo.strip():
        return examen.texto_completo
    lineas = [
        f"**{examen.titulo}**",
        f"{examen.asignatura} — {examen.curso}",
        f"Duración: {examen.duracion_minutos} min | Total: {examen.puntuacion_total} puntos",
        "",
        "**Preguntas:**",
    ]
    for p in examen.preguntas:
        lineas.append(f"{p.numero}. ({p.puntuacion} puntos) {p.enunciado}")
    if examen.solucionario:
        lineas.extend(["", "**Solucionario:**", examen.solucionario])
    if examen.fuentes:
        lineas.extend(["", "**Fuentes consultadas:**", *[f"- {f}" for f in examen.fuentes]])
    return "\n".join(lineas)


def render_veredicto(veredicto: VeredictoValidacion) -> str:
    """Vista legible del veredicto tipado."""
    cabecera = "VEREDICTO: APROBADO" if veredicto.aprobado else "VEREDICTO: CAMBIOS REQUERIDOS"
    partes = [cabecera]
    if veredicto.resumen:
        partes.append(veredicto.resumen)
    if veredicto.criterios_evaluados:
        partes.append("Criterios evaluados:")
        partes.extend(f"- {c}" for c in veredicto.criterios_evaluados)
    if veredicto.motivos:
        partes.append("Motivos / correcciones:")
        partes.extend(f"- {m}" for m in veredicto.motivos)
    return "\n".join(partes)
