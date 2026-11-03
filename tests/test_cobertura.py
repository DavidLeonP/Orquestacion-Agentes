"""Cobertura documental / Guardrail de relevancia (sin red ni Chroma)."""

from __future__ import annotations

from src.rag import cobertura as cob
from src.rag import context as rag_context


class _RetrieverFake:
    def __init__(self, chunks, scored, *, sem=None):
        self.chunks = chunks
        self._scored = scored
        self._sem = sem if sem is not None else [(c["id"], s) for c, s in scored]

    def buscar_con_score(self, consulta, k=4):
        return self._scored[:k]

    def _ranking_semantico_scored(self, consulta, n):
        return self._sem[:n]


def test_sin_user_id_no_bloquea():
    assert cob.evaluar_cobertura("cualquier tema", ("apuntes",)).suficiente is True


def test_kb_vacia_insuficiente(monkeypatch):
    token = rag_context.set_rag_user_id(99)
    try:
        monkeypatch.setattr(
            cob, "obtener_retriever", lambda uid, indice: _RetrieverFake([], [])
        )
        r = cob.evaluar_cobertura("ley de Ohm", ("apuntes",))
        assert r.suficiente is False
        assert "vacía" in r.motivo
    finally:
        rag_context.reset_rag_user_id(token)


def test_tema_ajeno_baja_relevancia(monkeypatch):
    token = rag_context.set_rag_user_id(99)
    try:
        chunks = [
            {
                "id": "c1",
                "texto": "La ley de Ohm relaciona tensión, intensidad y resistencia.",
                "metadatos": {
                    "fuente": "electricidad.pdf",
                    "asignatura": "Tecnología",
                    "curso": "3º ESO",
                },
            }
        ]
        # Similitud semántica muy baja (tema renacimiento vs electricidad)
        monkeypatch.setattr(
            cob,
            "obtener_retriever",
            lambda uid, indice: _RetrieverFake(chunks, [(chunks[0], 0.05)]),
        )
        r = cob.evaluar_cobertura(
            "teoría de colores de los artistas del renacimiento",
            ("apuntes",),
            umbral=0.38,
        )
        assert r.suficiente is False
        assert r.asignatura == "Tecnología"
        assert "electricidad.pdf" in r.fuentes
    finally:
        rag_context.reset_rag_user_id(token)


def test_tema_alineado_suficiente(monkeypatch):
    token = rag_context.set_rag_user_id(99)
    try:
        chunks = [
            {
                "id": "c1",
                "texto": "Circuitos en serie y paralelo. Ley de Ohm V=I*R.",
                "metadatos": {
                    "fuente": "apuntes_ohm.pdf",
                    "asignatura": "Tecnología",
                    "curso": "3º ESO",
                    "tema": "electricidad",
                },
            }
        ]
        monkeypatch.setattr(
            cob,
            "obtener_retriever",
            lambda uid, indice: _RetrieverFake(chunks, [(chunks[0], 0.72)]),
        )
        r = cob.evaluar_cobertura("Genera un examen sobre la ley de Ohm", ("apuntes",))
        assert r.suficiente is True
        assert r.temas_sugeridos[:1] == ["electricidad"]
        assert "apuntes_ohm.pdf" in r.resumen_para_prompt
    finally:
        rag_context.reset_rag_user_id(token)


def test_mensaje_rechazo_no_inventa():
    r = cob.CoberturaKB(suficiente=False, motivo="score bajo")
    assert "No inventaré" in r.mensaje_rechazo() or "no invent" in r.mensaje_rechazo().lower()
