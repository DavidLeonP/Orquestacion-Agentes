"""CRUD de conocimiento + ingest/reprocess."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.api.deps import get_current_user
from src.api.schemas import (
    ChunkOut,
    DocumentCreateIn,
    DocumentDetailOut,
    DocumentOut,
    DocumentUpdateIn,
    IngestOut,
)
from src.config import INDICES_NOMBRES
from src.db.models import Chunk, Document, User
from src.db.session import get_db
from src.ingestion.mysql_pipeline import ingest_pendientes, reprocess_documento
from src.rag.mysql_store import invalidar_cache_retriever

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def _validar_indice(indice: str) -> None:
    if indice not in INDICES_NOMBRES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"Índice inválido. Usa: {', '.join(INDICES_NOMBRES)}",
        )


@router.post("/{indice}/documents", response_model=DocumentOut, status_code=201)
def crear_documento(
    indice: str,
    body: DocumentCreateIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _validar_indice(indice)
    doc = Document(
        user_id=user.id,
        indice=indice,
        filename=body.filename,
        content_text=body.content_text,
        content_type="text/plain",
        status="pending",
        metadatos=body.metadatos or {"fuente": body.filename},
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


@router.get("/documents", response_model=list[DocumentOut])
def listar_documentos(
    indice: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(Document).filter(Document.user_id == user.id)
    if indice:
        _validar_indice(indice)
        q = q.filter(Document.indice == indice)
    return q.order_by(Document.id.desc()).all()


@router.get("/documents/{document_id}", response_model=DocumentDetailOut)
def detalle_documento(
    document_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    doc = (
        db.query(Document)
        .filter(Document.id == document_id, Document.user_id == user.id)
        .first()
    )
    if not doc:
        raise HTTPException(404, detail="Documento no encontrado")
    return doc


@router.patch("/documents/{document_id}", response_model=DocumentOut)
def actualizar_documento(
    document_id: int,
    body: DocumentUpdateIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    doc = (
        db.query(Document)
        .filter(Document.id == document_id, Document.user_id == user.id)
        .first()
    )
    if not doc:
        raise HTTPException(404, detail="Documento no encontrado")
    if body.content_text is not None:
        doc.content_text = body.content_text
    if body.filename is not None:
        doc.filename = body.filename
    if body.metadatos is not None:
        doc.metadatos = body.metadatos
    doc.status = "pending"
    doc.error_msg = None
    db.commit()
    db.refresh(doc)
    return doc


@router.delete("/documents/{document_id}", status_code=204)
def borrar_documento(
    document_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    doc = (
        db.query(Document)
        .filter(Document.id == document_id, Document.user_id == user.id)
        .first()
    )
    if not doc:
        raise HTTPException(404, detail="Documento no encontrado")
    db.delete(doc)
    db.commit()
    invalidar_cache_retriever(user.id)


@router.post("/ingest", response_model=IngestOut)
def ingest(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = ingest_pendientes(db, user.id)
    return IngestOut(**result)


@router.post("/documents/{document_id}/reprocess")
def reprocess(
    document_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return reprocess_documento(db, user.id, document_id)
    except LookupError:
        raise HTTPException(404, detail="Documento no encontrado") from None
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, detail=str(exc)) from exc


@router.get("/chunks", response_model=list[ChunkOut])
def listar_chunks(
    indice: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(Chunk).filter(Chunk.user_id == user.id)
    if indice:
        _validar_indice(indice)
        q = q.filter(Chunk.indice == indice)
    return q.order_by(Chunk.id.desc()).limit(200).all()
