"""Router de consultas en lenguaje natural al SQL Agent.

Restringido a docentes: la BD de negocio expone datos académicos
institucionales (notas, asistencia, matrícula), no material propio de un
alumno concreto.

HITL: si el Reflector marca duda semántica, la consulta pasa a
`waiting_clarification` y se reanuda con `POST /{id}/clarify`.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from src.api.deps import get_current_user
from src.api.schemas import SqlQueryClarifyIn, SqlQueryCreateIn, SqlQueryEventOut, SqlQueryOut
from src.api.services.sql_agent_runner import aclarar_query, crear_query, ejecutar_query
from src.db.models import SqlQuery, SqlQueryEvent, User
from src.db.session import get_db

router = APIRouter(prefix="/sql-queries", tags=["sql-agent"])


def _requerir_docente(user: User) -> None:
    if user.rol != "docente":
        raise HTTPException(403, detail="Solo docentes pueden consultar la BD de negocio")


@router.post("", response_model=SqlQueryOut, status_code=202)
def crear(
    body: SqlQueryCreateIn,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _requerir_docente(user)
    q = crear_query(db, user.id, body.pregunta)
    payload = SqlQueryOut.model_validate(q)
    background.add_task(ejecutar_query, payload.id, user.id, body.agent_db_uri)
    return payload


@router.post("/{query_id}/clarify", response_model=SqlQueryOut, status_code=202)
def clarificar(
    query_id: int,
    body: SqlQueryClarifyIn,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Reanuda una consulta en `waiting_clarification` con la aclaración del docente."""
    _requerir_docente(user)
    q = db.query(SqlQuery).filter(SqlQuery.id == query_id, SqlQuery.user_id == user.id).first()
    if not q:
        raise HTTPException(404, detail="Consulta no encontrada")
    if q.status != "waiting_clarification":
        raise HTTPException(409, detail="La consulta no está pendiente de aclaración")

    # Marca running de inmediato; el background reanuda el grafo y archiva en Chroma.
    q.status = "running"
    db.add(
        SqlQueryEvent(
            sql_query_id=q.id,
            tipo="aclaracion_recibida",
            payload={"aclaracion": body.aclaracion[:2000]},
        )
    )
    db.commit()
    db.refresh(q)
    payload = SqlQueryOut.model_validate(q)
    background.add_task(
        aclarar_query,
        payload.id,
        user.id,
        body.aclaracion,
        body.agent_db_uri,
    )
    return payload


@router.get("", response_model=list[SqlQueryOut])
def listar(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _requerir_docente(user)
    return (
        db.query(SqlQuery)
        .filter(SqlQuery.user_id == user.id)
        .order_by(SqlQuery.id.desc())
        .limit(50)
        .all()
    )


@router.get("/{query_id}", response_model=SqlQueryOut)
def detalle(query_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _requerir_docente(user)
    q = db.query(SqlQuery).filter(SqlQuery.id == query_id, SqlQuery.user_id == user.id).first()
    if not q:
        raise HTTPException(404, detail="Consulta no encontrada")
    return q


@router.get("/{query_id}/events", response_model=list[SqlQueryEventOut])
def events(query_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _requerir_docente(user)
    q = db.query(SqlQuery).filter(SqlQuery.id == query_id, SqlQuery.user_id == user.id).first()
    if not q:
        raise HTTPException(404, detail="Consulta no encontrada")
    return (
        db.query(SqlQueryEvent)
        .filter(SqlQueryEvent.sql_query_id == query_id)
        .order_by(SqlQueryEvent.id)
        .all()
    )
