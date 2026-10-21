"""Cola de extracción e indexación.

La petición HTTP solo guarda el documento y vuelve. Un hilo del proceso de la
API extrae el texto (PDF o vídeo) y luego lo indexa, anotando cada paso en
`document.metadatos["progreso"]` para que la interfaz lo pueda leer.
"""

from __future__ import annotations

import logging
import queue
import threading
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from src.config import DIR_INBOX
from src.db.models import Document
from src.db.session import SessionLocal
from src.ingestion.extractors.pdf import extraer_pdf
from src.ingestion.extractors.video import VIDEO_SUFFIXES, extraer_video
from src.ingestion.mysql_pipeline import indexar_documento

logger = logging.getLogger("orquestacion.ingesta")

_cola: queue.Queue[tuple[int, bool]] = queue.Queue()
_en_curso: set[int] = set()
_lock = threading.Lock()
_worker: threading.Thread | None = None


def ruta_permitida(user_id: int, ruta: str) -> Path:
    """Acepta solo un archivo dentro de storage/inbox/<user_id>/."""
    base = (DIR_INBOX / str(user_id)).resolve()
    path = Path(ruta).resolve()
    if not path.is_relative_to(base):
        raise ValueError("El archivo tiene que estar en la bandeja de este usuario")
    if not path.is_file():
        raise ValueError(f"No está el archivo: {path.name}")
    return path


def esta_en_cola(document_id: int) -> bool:
    with _lock:
        return document_id in _en_curso


def registrar_paso(db: Session, doc: Document, paso: str, detalle: str) -> None:
    """Añade una línea al historial del documento y la confirma."""
    meta = dict(doc.metadatos or {})
    log = list(meta.get("progreso") or [])
    log.append(
        {
            "ts": datetime.now(timezone.utc).strftime("%H:%M:%S"),
            "paso": paso,
            "detalle": (detalle or "")[:300],
        }
    )
    meta["progreso"] = log[-80:]
    meta["paso"] = paso
    doc.metadatos = meta
    flag_modified(doc, "metadatos")
    db.commit()
    logger.info("doc %s [%s] %s", doc.id, paso, detalle)


def encolar(document_id: int, *, reextraer: bool = False) -> bool:
    """Mete el documento en la cola. False si ya estaba."""
    global _worker
    with _lock:
        if document_id in _en_curso:
            return False
        _en_curso.add(document_id)
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_bucle, name="oa-indexacion", daemon=True)
            _worker.start()
    _cola.put((document_id, reextraer))
    return True


def _bucle() -> None:
    while True:
        document_id, reextraer = _cola.get()
        try:
            procesar_documento(document_id, reextraer=reextraer)
        except Exception:
            logger.exception("Fallo no capturado en document_id=%s", document_id)
        finally:
            with _lock:
                _en_curso.discard(document_id)
            _cola.task_done()


def _marcar_error(db: Session, document_id: int, exc: Exception) -> None:
    db.rollback()
    doc = db.get(Document, document_id)
    if doc is None:
        return
    doc.status = "error"
    doc.error_msg = str(exc)[:2000]
    db.commit()
    registrar_paso(db, doc, "error", str(exc)[:500])


def _extraer_a_documento(db: Session, doc: Document, ruta: Path) -> None:
    if not ruta.is_file():
        doc.status = "error"
        doc.error_msg = f"No está el archivo: {ruta.name}"
        registrar_paso(db, doc, "error", doc.error_msg)
        return

    mb = ruta.stat().st_size / (1024 * 1024)
    doc.status = "extracting"
    db.commit()
    registrar_paso(db, doc, "guardado", f"{ruta.name} · {mb:.1f} MB")

    def aviso(paso: str, detalle: str) -> None:
        registrar_paso(db, doc, paso, detalle)

    suffix = ruta.suffix.lower()
    if suffix == ".pdf":
        aviso("pdf", "extrayendo la capa de texto")
        extr = extraer_pdf(ruta, dry_run=False)
        texto = extr.content_text
        extra = dict(extr.metadatos or {})
    elif suffix in VIDEO_SUFFIXES:
        extr = extraer_video(ruta, dry_run=False, on_progress=aviso)
        texto = extr.content_text
        extra = dict(extr.metadatos or {})
    else:
        aviso("texto", "leyendo el archivo")
        texto = ruta.read_text(encoding="utf-8", errors="replace")
        extra = {"fuente": ruta.name, "media_tipo": "texto"}

    if not (texto or "").strip():
        doc.status = "error"
        doc.error_msg = "Sin texto extraíble"
        registrar_paso(db, doc, "error", doc.error_msg)
        return

    actual = dict(doc.metadatos or {})
    actual.update(extra)
    actual["storage_path"] = str(ruta)
    doc.metadatos = actual
    doc.content_text = texto
    doc.status = "indexing"
    flag_modified(doc, "metadatos")
    db.commit()
    registrar_paso(db, doc, "texto", f"{len(texto)} caracteres listos para indexar")


def procesar_documento(document_id: int, *, reextraer: bool = False) -> None:
    db = SessionLocal()
    try:
        doc = db.get(Document, document_id)
        if doc is None:
            return
        ruta_txt = (doc.metadatos or {}).get("storage_path")
        vacio = not (doc.content_text or "").strip()
        if (reextraer or vacio) and ruta_txt:
            _extraer_a_documento(db, doc, Path(ruta_txt))
            doc = db.get(Document, document_id)
            if doc is None or doc.status == "error":
                return
        elif vacio:
            doc.status = "error"
            doc.error_msg = "No hay texto ni archivo para indexar"
            registrar_paso(db, doc, "error", doc.error_msg)
            return

        doc.status = "indexing"
        db.commit()

        def on_step(paso: str, detalle: str) -> None:
            registrar_paso(db, doc, paso, detalle)

        n = indexar_documento(db, doc, on_step=on_step)
        doc = db.get(Document, document_id)
        if doc is not None:
            registrar_paso(db, doc, "listo", f"{n} fragmentos indexados")
    except Exception as exc:  # noqa: BLE001
        _marcar_error(db, document_id, exc)
    finally:
        db.close()
