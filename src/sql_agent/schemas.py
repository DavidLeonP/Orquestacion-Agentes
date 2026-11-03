"""Contratos tipados del SQL Agent (validación + HITL de aclaración)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class VeredictoSql(BaseModel):
    """Resultado de validar una respuesta del SQL Agent."""

    aprobado: bool
    necesita_aclaracion: bool = Field(
        default=False,
        description="True si la pregunta es ambigua y hace falta aclaración humana",
    )
    motivos: list[str] = Field(default_factory=list)
    pregunta_aclaracion: str = Field(
        default="",
        description="Pregunta concreta al docente cuando necesita_aclaracion",
    )
    resumen: str = ""
    etapa: Literal["determinista", "llm"] = "determinista"


class PayloadAclaracionSql(BaseModel):
    """Payload del interrupt HITL cuando el Reflector pide aclaración."""

    mensaje: str = "El SQL Agent necesita una aclaración para no alucinar el filtro."
    pregunta_original: str
    borrador_respuesta: str = ""
    sql_propuesto: str | None = None
    motivos: list[str] = Field(default_factory=list)
    pregunta_aclaracion: str
