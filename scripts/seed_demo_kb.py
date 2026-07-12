"""Carga los documentos demo de data/ como KB de un usuario."""

from pathlib import Path

from src.config import INDICES, RAIZ
from src.db.models import Document, User
from src.db.session import SessionLocal
from src.ingestion.mysql_pipeline import ingest_pendientes


def seed(email: str = "demo@instituto.local") -> None:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if user is None:
            raise SystemExit(
                f"Usuario {email} no existe. Regístralo primero vía POST /auth/register"
            )

        creados = 0
        for indice, carpeta in INDICES.items():
            if not carpeta.exists():
                continue
            for ruta in sorted(carpeta.glob("*")):
                if ruta.suffix.lower() not in {".txt", ".md"}:
                    continue
                exists = (
                    db.query(Document)
                    .filter(
                        Document.user_id == user.id,
                        Document.indice == indice,
                        Document.filename == ruta.name,
                    )
                    .first()
                )
                if exists:
                    continue
                db.add(
                    Document(
                        user_id=user.id,
                        indice=indice,
                        filename=ruta.name,
                        content_text=ruta.read_text(encoding="utf-8"),
                        content_type="text/plain",
                        status="pending",
                        metadatos={"fuente": ruta.name},
                    )
                )
                creados += 1
        db.commit()
        print(f"Documentos pendientes creados: {creados}")
        result = ingest_pendientes(db, user.id)
        print(f"Ingest: {result}")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
