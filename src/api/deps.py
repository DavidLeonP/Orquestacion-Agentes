"""Dependencias FastAPI: DB y usuario autenticado."""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from src.api.security import decode_access_token
from src.db.models import User
from src.db.session import get_db

bearer = HTTPBearer(auto_error=False)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None or not creds.credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Token requerido")
    try:
        payload = decode_access_token(creds.credentials)
        user_id = int(payload["sub"])
    except (ValueError, KeyError, TypeError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Token inválido") from None

    user = db.get(User, user_id)
    if user is None or not user.activo:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Usuario no válido")
    return user
