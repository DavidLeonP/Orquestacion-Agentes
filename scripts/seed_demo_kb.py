"""Carga los documentos demo de data/ como KB de un usuario."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db.models import User
from src.db.session import SessionLocal
from src.ingestion.carpeta_data import sincronizar_carpeta_data


def seed(email: str = "demo@instituto.local") -> None:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
    finally:
        db.close()
    if user is None:
        raise SystemExit(
            f"Usuario {email} no existe. Regístralo primero vía POST /auth/register"
        )
    print(f"Ingest: {sincronizar_carpeta_data(user.id)}")


if __name__ == "__main__":
    seed()
