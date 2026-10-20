"""Criterios de la rúbrica extraídos por LLM y cacheados por (user_id, hash del texto)."""

from __future__ import annotations

import pytest

from src.agents.schemas import CriteriosRubrica
from src.orchestrator import criterios


@pytest.fixture
def entorno(monkeypatch):
    textos = {1: "La rúbrica exige una pregunta de seguridad.", 2: "Rúbrica del usuario 2: 40% numérico."}
    llamadas = []

    def _extraer(texto):
        llamadas.append(texto)
        return CriteriosRubrica(requiere_seguridad="seguridad" in texto,
                                pct_min_numerico=0.4 if "40%" in texto else 0)

    monkeypatch.setattr(criterios, "_texto_rubricas", lambda uid: textos[uid])
    monkeypatch.setattr(criterios, "extraer_criterios", _extraer)
    monkeypatch.setattr(criterios, "_cache", {})
    return textos, llamadas


def test_cache_por_hash(entorno):
    _, llamadas = entorno
    c1 = criterios.cargar_criterios(1)
    c2 = criterios.cargar_criterios(1)
    assert c1.requiere_seguridad is True and c1 is c2
    assert len(llamadas) == 1


def test_cache_se_invalida_al_cambiar_el_texto(entorno):
    textos, llamadas = entorno
    assert criterios.cargar_criterios(1).requiere_seguridad is True
    textos[1] = "Nueva rúbrica sin requisitos."
    assert criterios.cargar_criterios(1).requiere_seguridad is False
    assert len(llamadas) == 2


def test_aislamiento_entre_usuarios(entorno):
    textos, llamadas = entorno
    textos[2] = textos[1]  # mismo texto, distinto usuario: entradas de caché separadas
    criterios.cargar_criterios(1)
    criterios.cargar_criterios(2)
    assert len(llamadas) == 2
    assert {k[0] for k in criterios._cache} == {1, 2}


def test_criterios_distintos_por_usuario(entorno):
    assert criterios.cargar_criterios(1).requiere_seguridad is True
    c2 = criterios.cargar_criterios(2)
    assert c2.requiere_seguridad is False and c2.pct_min_numerico == 0.4


@pytest.mark.parametrize("texto", ["", "   \n  "])
def test_rubrica_vacia_defaults_sin_llm(entorno, monkeypatch, texto):
    _, llamadas = entorno
    monkeypatch.setattr(criterios, "_texto_rubricas", lambda uid: texto)
    assert criterios.cargar_criterios(1) == CriteriosRubrica()
    assert llamadas == [] and criterios._cache == {}


def test_error_de_bd_defaults(entorno, monkeypatch):
    _, llamadas = entorno

    def _falla(uid):
        raise RuntimeError("MySQL caído")

    monkeypatch.setattr(criterios, "_texto_rubricas", _falla)
    assert criterios.cargar_criterios(1) == CriteriosRubrica()
    assert llamadas == []


def test_extraer_criterios_fallback_si_el_llm_falla(monkeypatch):
    from src.agents import base

    class Lanza:
        def invoke(self, prompt):
            raise ConnectionError("sin red")

    monkeypatch.setattr(base, "get_structured_model", lambda *a, **k: Lanza())
    assert criterios.extraer_criterios("rúbrica") is None  # None = el LLM falló (no cachear)


def test_extraer_criterios_salida_valida_y_prompt(monkeypatch):
    from src.agents import base

    prompts = []

    class Modelo:
        def invoke(self, prompt):
            prompts.append(prompt)
            return {"requiere_seguridad": True, "pct_min_numerico": 0.4, "tipos_minimos": 3}

    monkeypatch.setattr(base, "get_structured_model", lambda *a, **k: Modelo())
    c = criterios.extraer_criterios("TEXTO_RUBRICA")
    assert c == CriteriosRubrica(requiere_seguridad=True, pct_min_numerico=0.4, tipos_minimos=3)
    assert "TEXTO_RUBRICA" in prompts[0]


def test_extraer_criterios_fuera_de_rango_fallback(monkeypatch):
    from src.agents import base

    class Modelo:
        def invoke(self, prompt):
            return {"pct_min_numerico": 40}  # 40 en vez de 0.4: inválido (le=1)

    monkeypatch.setattr(base, "get_structured_model", lambda *a, **k: Modelo())
    assert criterios.extraer_criterios("x") is None


def test_texto_rubricas_concatena_y_trunca(monkeypatch):
    filas = [("a" * 5000,), ("b" * 5000,)]
    cerradas = []

    class Q:
        def filter(self, *a):
            return self

        def order_by(self, *a):
            return self

        def all(self):
            return filas

    class Db:
        def query(self, *a):
            return Q()

        def close(self):
            cerradas.append(1)

    monkeypatch.setattr(criterios, "SessionLocal", lambda: Db())
    texto = criterios._texto_rubricas(1)
    assert len(texto) == criterios.MAX_CHARS_RUBRICA and texto.startswith("a") and "\n" in texto
    assert cerradas == [1]


# Regresión (criterios.py): antes se cacheaba el fallback tras un fallo del LLM.
def test_fallo_del_llm_no_se_cachea(monkeypatch):
    from src.agents import base

    monkeypatch.setattr(criterios, "_texto_rubricas", lambda uid: "Exige seguridad.")
    monkeypatch.setattr(criterios, "_cache", {})
    estado = {"falla": True}

    class Modelo:
        def invoke(self, prompt):
            if estado["falla"]:
                raise TimeoutError("timeout")
            return {"requiere_seguridad": True}

    monkeypatch.setattr(base, "get_structured_model", lambda *a, **k: Modelo())
    assert criterios.cargar_criterios(1) == CriteriosRubrica()
    assert criterios._cache == {}
    estado["falla"] = False
    assert criterios.cargar_criterios(1).requiere_seguridad is True
    assert len(criterios._cache) == 1
