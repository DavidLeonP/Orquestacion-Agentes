"""Carga/preparación de módulos de conocimiento del profesor (PDF + vídeo).

No embebe por defecto. El flujo seguro para métricas es:

  inventariar_modulo → estimar_coste_modulo (dry_run, sin ASR ni embeddings)
  preparar_modulo(..., dry_run=False)  # extrae texto / transcribe
  indexar vía mysql_pipeline solo si commit_ingest=True
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from sqlalchemy.orm import Session

from src.config import DIR_STORAGE, RAIZ
from src.db.models import Document
from src.ingestion.cost_estimate import SourceEstimate, comparar_perfiles, estimar_fuente
from src.ingestion.extractors import (
    VIDEO_SUFFIXES,
    ExtractionResult,
    MediaInventoryItem,
    extraer_pdf,
    extraer_video,
    inventariar_pdf,
    inventariar_video,
)
from src.ingestion.mysql_pipeline import indexar_documento

logger = logging.getLogger("orquestacion.ingestion.module_media")

TEXT_SUFFIXES = {".txt", ".md"}
PDF_SUFFIXES = {".pdf"}

IndiceNombre = Literal["apuntes", "examenes", "rubricas", "curriculo"]


@dataclass
class ModuleScan:
    module_path: str
    items: list[MediaInventoryItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "module_path": self.module_path,
            "items": [i.to_dict() for i in self.items],
            "resumen": {
                "pdfs": sum(1 for i in self.items if i.kind == "pdf"),
                "videos": sum(1 for i in self.items if i.kind == "video"),
                "textos": sum(1 for i in self.items if i.kind == "text"),
                "bytes_totales": sum(i.size_bytes for i in self.items),
                "duration_sec_total": sum(
                    (i.duration_sec or 0.0) for i in self.items if i.kind == "video"
                ),
                "pdf_chars_total": sum(
                    (i.chars_extracted or 0) for i in self.items if i.kind == "pdf"
                ),
            },
        }


def resolver_ruta_modulo(modulo: str | Path) -> Path:
    ruta = Path(modulo)
    if not ruta.is_absolute():
        cand = RAIZ / ruta
        if cand.exists():
            ruta = cand
        else:
            ruta = RAIZ / "contabilidadFinaciera" if modulo == "contabilidadFinaciera" else cand
    if not ruta.exists():
        raise FileNotFoundError(f"Módulo no encontrado: {ruta}")
    return ruta.resolve()


def inventariar_modulo(modulo: str | Path) -> ModuleScan:
    root = resolver_ruta_modulo(modulo)
    items: list[MediaInventoryItem] = []
    for ruta in sorted(root.rglob("*")):
        if not ruta.is_file() or ruta.name.startswith("."):
            continue
        suf = ruta.suffix.lower()
        if suf in PDF_SUFFIXES:
            items.append(inventariar_pdf(ruta))
        elif suf in VIDEO_SUFFIXES:
            items.append(inventariar_video(ruta))
        elif suf in TEXT_SUFFIXES:
            texto = ruta.read_text(encoding="utf-8", errors="replace")
            items.append(
                MediaInventoryItem(
                    path=str(ruta.resolve()),
                    kind="text",
                    filename=ruta.name,
                    size_bytes=ruta.stat().st_size,
                    chars_extracted=len(texto),
                )
            )
    return ModuleScan(module_path=str(root), items=items)


def _frontmatter(asignatura: str, titulo: str, tipo: str, extra: dict[str, Any]) -> str:
    lineas = [
        "---",
        f"asignatura: {asignatura}",
        f"titulo: {titulo}",
        f"tipo: {tipo}",
        "anio: 2025",
    ]
    for k, v in extra.items():
        if v is None:
            continue
        lineas.append(f"{k}: {v}")
    lineas.append("---")
    lineas.append("")
    return "\n".join(lineas)


def estimar_coste_modulo(modulo: str | Path) -> dict[str, Any]:
    """Inventario + coste OpenAI vs USFQ sin ASR ni embeddings."""
    from src.ingestion.extractors.video import estimar_chars_transcripcion

    scan = inventariar_modulo(modulo)
    sources: list[SourceEstimate] = []
    for item in scan.items:
        if item.kind == "pdf":
            sources.append(
                estimar_fuente(
                    filename=item.filename,
                    kind="pdf",
                    chars=item.chars_extracted or 0,
                )
            )
        elif item.kind == "video":
            chars = estimar_chars_transcripcion(item.duration_sec)
            sources.append(
                estimar_fuente(
                    filename=item.filename,
                    kind="video",
                    chars=chars,
                    duration_sec=item.duration_sec,
                )
            )
        elif item.kind == "text":
            sources.append(
                estimar_fuente(
                    filename=item.filename,
                    kind="text",
                    chars=item.chars_extracted or 0,
                )
            )
    comparativa = comparar_perfiles(sources)
    return {
        "inventario": scan.to_dict(),
        **comparativa,
    }


def preparar_modulo(
    modulo: str | Path,
    *,
    dry_run: bool = True,
    asignatura: str | None = None,
    indice: IndiceNombre = "apuntes",
    language: str = "es",
    out_dir: Path | None = None,
) -> dict[str, Any]:
    """Extrae PDF / transcribe vídeo → textos en storage (o solo estima).

    dry_run=True (default): no llama a Whisper ni escribe transcripts.
    """
    root = resolver_ruta_modulo(modulo)
    nombre_mod = root.name
    asignatura = asignatura or nombre_mod
    destino = out_dir or (DIR_STORAGE / "extracted" / nombre_mod)
    if not dry_run:
        destino.mkdir(parents=True, exist_ok=True)

    resultados: list[ExtractionResult] = []
    for ruta in sorted(root.rglob("*")):
        if not ruta.is_file() or ruta.name.startswith("."):
            continue
        suf = ruta.suffix.lower()
        if suf in PDF_SUFFIXES:
            res = extraer_pdf(ruta, dry_run=dry_run)
        elif suf in VIDEO_SUFFIXES:
            res = extraer_video(ruta, dry_run=dry_run, language=language)
        elif suf in TEXT_SUFFIXES:
            texto = ruta.read_text(encoding="utf-8", errors="replace")
            res = ExtractionResult(
                filename=ruta.name,
                content_text="" if dry_run else texto,
                content_type="text/plain",
                source_path=str(ruta.resolve()),
                metadatos={"fuente": ruta.name, "media_tipo": "text"},
                dry_run=dry_run,
                estimated_chars=len(texto),
            )
        else:
            continue

        if not dry_run and res.content_text:
            cab = _frontmatter(
                asignatura,
                titulo=ruta.stem,
                tipo=res.metadatos.get("media_tipo", "apuntes"),
                extra={
                    "modulo": nombre_mod,
                    "indice": indice,
                    "fuente_original": ruta.name,
                    "duration_sec": res.estimated_duration_sec,
                },
            )
            cuerpo = cab + res.content_text
            res.content_text = cuerpo
            (destino / res.filename).write_text(cuerpo, encoding="utf-8")
            meta_path = destino / f"{Path(res.filename).stem}.meta.json"
            meta_path.write_text(
                json.dumps(res.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        resultados.append(res)

    estimacion = estimar_coste_modulo(root)
    return {
        "module_path": str(root),
        "dry_run": dry_run,
        "out_dir": str(destino) if not dry_run else None,
        "indice_destino": indice,
        "extracciones": [r.to_dict() for r in resultados],
        "estimacion": estimacion,
    }


def commit_extracted_a_mysql(
    db: Session,
    *,
    user_id: int,
    extracted_dir: Path,
    indice: IndiceNombre = "apuntes",
    indexar: bool = False,
) -> dict[str, Any]:
    """Crea Documents pending desde textos ya extraídos. indexar=False por defecto."""
    creados = []
    for ruta in sorted(extracted_dir.glob("*.txt")) + sorted(extracted_dir.glob("*.md")):
        texto = ruta.read_text(encoding="utf-8")
        meta_file = extracted_dir / f"{ruta.stem}.meta.json"
        metadatos: dict[str, Any] = {"fuente": ruta.name}
        if meta_file.exists():
            try:
                metadatos.update(json.loads(meta_file.read_text(encoding="utf-8")).get("metadatos") or {})
            except json.JSONDecodeError:
                pass
        exists = (
            db.query(Document)
            .filter(
                Document.user_id == user_id,
                Document.indice == indice,
                Document.filename == ruta.name,
            )
            .first()
        )
        if exists:
            exists.content_text = texto
            exists.status = "pending"
            exists.error_msg = None
            exists.metadatos = metadatos
            doc = exists
        else:
            doc = Document(
                user_id=user_id,
                indice=indice,
                filename=ruta.name,
                content_text=texto,
                content_type="text/plain",
                status="pending",
                metadatos=metadatos,
            )
            db.add(doc)
        db.commit()
        db.refresh(doc)
        entry: dict[str, Any] = {"document_id": doc.id, "filename": doc.filename}
        if indexar:
            entry["chunks"] = indexar_documento(db, doc)
        creados.append(entry)
    return {"creados": len(creados), "indexados": bool(indexar), "detalle": creados}


def guardar_informe_estimacion(
    modulo: str | Path,
    destino: Path | None = None,
) -> Path:
    """Escribe JSON de métricas (sin ejecutar ingest/embeddings)."""
    data = estimar_coste_modulo(modulo)
    out = destino or (
        DIR_STORAGE / "metrics" / f"{resolver_ruta_modulo(modulo).name}-ingest-estimate.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
