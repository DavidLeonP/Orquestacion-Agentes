"""Router de solicitudes al orquestador."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from src.api.deps import get_current_user
from src.api.schemas import ApproveIn, RequestCreateIn, RequestEventOut, RequestOut
from src.api.services.orchestrator_runner import (
    aprobar_request,
    crear_request,
    ejecutar_request,
)
from src.db.models import Request, RequestEvent, User
from src.db.session import get_db

router = APIRouter(prefix="/requests", tags=["requests"])


@router.post("", response_model=RequestOut, status_code=202)
def crear(
    body: RequestCreateIn,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    req = crear_request(db, user.id, user.rol, body.peticion)
    background.add_task(ejecutar_request, req.id)
    return req


@router.get("", response_model=list[RequestOut])
def listar(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(Request)
        .options(joinedload(Request.approval))
        .filter(Request.user_id == user.id)
        .order_by(Request.id.desc())
        .limit(50)
        .all()
    )


@router.get("/{request_id}", response_model=RequestOut)
def detalle(
    request_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    req = (
        db.query(Request)
        .options(joinedload(Request.approval))
        .filter(Request.id == request_id, Request.user_id == user.id)
        .first()
    )
    if not req:
        raise HTTPException(404, detail="Solicitud no encontrada")
    return req


@router.post("/{request_id}/approve", response_model=RequestOut)
def approve(
    request_id: int,
    body: ApproveIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.rol != "docente":
        raise HTTPException(403, detail="Solo docentes pueden aprobar material")
    try:
        req = aprobar_request(request_id, user.id, body.decision)
    except LookupError:
        raise HTTPException(404, detail="Solicitud no encontrada") from None
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    # Recargar con approval
    return (
        db.query(Request)
        .options(joinedload(Request.approval))
        .filter(Request.id == req.id)
        .first()
    )


@router.get("/{request_id}/events", response_model=list[RequestEventOut])
def events(
    request_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    req = (
        db.query(Request)
        .filter(Request.id == request_id, Request.user_id == user.id)
        .first()
    )
    if not req:
        raise HTTPException(404, detail="Solicitud no encontrada")
    return (
        db.query(RequestEvent)
        .filter(RequestEvent.request_id == request_id)
        .order_by(RequestEvent.id)
        .all()
    )
