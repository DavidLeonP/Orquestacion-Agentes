"""Memoria Chroma de aclaraciones SQL (mock embeddings / cliente)."""

from __future__ import annotations

from src.memory import clarificaciones_sql as mem
from src.sql_agent.reflexion import verificar_respuesta


def test_seed_texto_canónico_sin_chroma(monkeypatch):
    """archivar/seed no rompe si Chroma falla: fail-soft."""
    monkeypatch.setattr(
        mem,
        "coleccion_vectores",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("chroma down")),
    )
    assert mem.seed_anio_pasado("t-test") is None
    assert mem.recordar("t-test", "año pasado") == []


def test_verificar_respeta_aclaracion_en_contexto():
    v = verificar_respuesta(
        "estudiantes matriculados el año pasado",
        "83 alumnos",
        "SELECT * FROM estudiantes WHERE anio_ingreso = 2022",
        clarificaciones=[
            "Aclaración: NO uses anio_ingreso para matrículas por periodo relativo."
        ],
    )
    assert not v.aprobado
    assert any("aclaración ya aprendida" in m.lower() for m in v.motivos)
