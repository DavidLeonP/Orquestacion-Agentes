"""Router de consultas en lenguaje natural al SQL Agent.

Restringido a docentes: la BD de negocio expone datos académicos
institucionales (notas, asistencia, matrícula), no material propio de un
alumno concreto.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from src.api.deps import get_current_user
from src.api.schemas import SqlQueryCreateIn, SqlQueryEventOut, SqlQueryOut
from src.api.services.sql_agent_runner import crear_query, ejecutar_query
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
    # Serializar antes del background: si la inferencia es lenta, la sesión
    # HTTP no debe depender de que el objeto ORM siga vivo tras el commit.
    payload = SqlQueryOut.model_validate(q)
    background.add_task(ejecutar_query, payload.id, user.id, body.agent_db_uri)
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
