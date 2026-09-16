"""Tipos compartidos para extracción de medios (PDF / vídeo)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ExtractionResult:
    """Texto listo para crear un Document (content_text) + metadatos."""

    filename: str
    content_text: str
    content_type: str
    source_path: str
    metadatos: dict[str, Any] = field(default_factory=dict)
    dry_run: bool = False
    estimated_chars: int | None = None
    estimated_duration_sec: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MediaInventoryItem:
    path: str
    kind: str  # pdf | video | text
    filename: str
    size_bytes: int
    pages: int | None = None
    duration_sec: float | None = None
    chars_extracted: int | None = None
    empty_pages: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
