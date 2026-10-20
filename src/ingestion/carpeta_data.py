"""Carga los documentos de data/<indice>/ en la KB MySQL de un usuario.

Lo usan `python main.py ingestar`, POST /api/v1/ingestar (legado) y
scripts/seed_demo_kb.py. Solo crea los que el usuario aún no tiene y los indexa.
"""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

from src.config import INDICES
from src.db.models import Document
from src.db.session import SessionLocal
from src.ingestion.mysql_pipeline import ingest_pendientes

EXTENSIONES = {".txt", ".md", ".pdf"}


def _leer(ruta: Path) -> str:
    if ruta.suffix.lower() == ".pdf":
        return "\n".join(p.extract_text() or "" for p in PdfReader(str(ruta)).pages)
    return ruta.read_text(encoding="utf-8")


def sincronizar_carpeta_data(user_id: int) -> dict:
    """Crea los Document pendientes que falten y los indexa. Devuelve el resultado del ingest."""
    db = SessionLocal()
    try:
        existentes = {
            (d.indice, d.filename)
            for d in db.query(Document.indice, Document.filename).filter(Document.user_id == user_id)
        }
        creados, ilegibles = 0, []
        for indice, carpeta in INDICES.items():
            for ruta in sorted(carpeta.glob("*")) if carpeta.exists() else []:
                if ruta.suffix.lower() not in EXTENSIONES or (indice, ruta.name) in existentes:
                    continue
                try:
                    texto = _leer(ruta)
                except Exception as exc:  # noqa: BLE001 - un archivo malo no frena al resto
                    ilegibles.append({"filename": ruta.name, "error": str(exc)[:200]})
                    continue
                db.add(Document(
                    user_id=user_id,
                    indice=indice,
                    filename=ruta.name,
                    content_text=texto,
                    content_type="text/plain",
                    status="pending",
                    metadatos={"fuente": ruta.name},
                ))
                creados += 1
        db.commit()
        return {"documentos_nuevos": creados, "ilegibles": ilegibles, **ingest_pendientes(db, user_id)}
    finally:
        db.close()
