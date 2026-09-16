"""Extracción de texto desde PDF (capa de texto; OCR opcional no incluido)."""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

from src.ingestion.extractors.types import ExtractionResult, MediaInventoryItem


def inventariar_pdf(ruta: Path) -> MediaInventoryItem:
    reader = PdfReader(str(ruta))
    chars = 0
    empty = 0
    for page in reader.pages:
        texto = page.extract_text() or ""
        if not texto.strip():
            empty += 1
        chars += len(texto)
    return MediaInventoryItem(
        path=str(ruta.resolve()),
        kind="pdf",
        filename=ruta.name,
        size_bytes=ruta.stat().st_size,
        pages=len(reader.pages),
        chars_extracted=chars,
        empty_pages=empty,
    )


def extraer_pdf(ruta: Path, *, dry_run: bool = False) -> ExtractionResult:
    """Devuelve el texto del PDF o solo metadatos/estimación si dry_run."""
    inv = inventariar_pdf(ruta)
    metadatos = {
        "fuente": ruta.name,
        "media_tipo": "pdf",
        "pages": inv.pages,
        "size_bytes": inv.size_bytes,
        "empty_pages": inv.empty_pages,
    }
    if dry_run:
        return ExtractionResult(
            filename=ruta.name,
            content_text="",
            content_type="application/pdf",
            source_path=str(ruta.resolve()),
            metadatos=metadatos,
            dry_run=True,
            estimated_chars=inv.chars_extracted,
        )

    reader = PdfReader(str(ruta))
    texto = "\n".join(page.extract_text() or "" for page in reader.pages)
    return ExtractionResult(
        filename=ruta.name,
        content_text=texto,
        content_type="application/pdf",
        source_path=str(ruta.resolve()),
        metadatos=metadatos,
        dry_run=False,
        estimated_chars=len(texto),
    )
