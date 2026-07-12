"""Schemas Pydantic de la API."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class RegisterIn(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=6)
    rol: Literal["docente", "alumno"]


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    email: str
    rol: str
    activo: bool

    model_config = {"from_attributes": True}


class DocumentCreateIn(BaseModel):
    filename: str
    content_text: str
    metadatos: dict[str, Any] | None = None


class DocumentUpdateIn(BaseModel):
    content_text: str | None = None
    filename: str | None = None
    metadatos: dict[str, Any] | None = None


class DocumentOut(BaseModel):
    id: int
    user_id: int
    indice: str
    filename: str
    status: str
    metadatos: dict[str, Any] | None
    error_msg: str | None
    created_at: datetime | None
    updated_at: datetime | None

    model_config = {"from_attributes": True}


class DocumentDetailOut(DocumentOut):
    content_text: str


class IngestOut(BaseModel):
    procesados: int
    errores: int
    detalle: list[dict[str, Any]]


class ChunkOut(BaseModel):
    id: int
    document_id: int
    indice: str
    chunk_uid: str
    texto: str
    metadatos: dict[str, Any] | None
    position: int

    model_config = {"from_attributes": True}


class RequestCreateIn(BaseModel):
    peticion: str = Field(min_length=1)
    alumno_id: str | None = None


class ApproveIn(BaseModel):
    decision: Literal["si", "no", "sí", "yes", "y", "n"]


class ApprovalOut(BaseModel):
    id: int
    borrador: str
    veredicto: str
    decision: str

    model_config = {"from_attributes": True}


class RequestOut(BaseModel):
    id: int
    thread_id: str
    rol: str
    peticion: str
    status: str
    agente_destino: str | None
    respuesta_final: str | None
    error: str | None
    created_at: datetime | None
    updated_at: datetime | None
    approval: ApprovalOut | None = None

    model_config = {"from_attributes": True}


class RequestEventOut(BaseModel):
    id: int
    tipo: str
    payload: dict[str, Any] | None
    created_at: datetime | None

    model_config = {"from_attributes": True}
