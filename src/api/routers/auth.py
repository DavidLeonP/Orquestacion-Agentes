"""Router de autenticación."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.api.deps import get_current_user
from src.api.schemas import LoginIn, RegisterIn, TokenOut, UserOut
from src.api.security import create_access_token, hash_password, verify_password
from src.db.models import User
from src.db.session import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Email ya registrado")
    user = User(
        email=body.email.lower(),
        password_hash=hash_password(body.password),
        rol=body.rol,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email.lower()).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Credenciales inválidas")
    if not user.activo:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Usuario inactivo")
    token = create_access_token(user.id, user.email, user.rol)
    return TokenOut(access_token=token)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
