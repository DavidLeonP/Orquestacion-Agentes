"""Memoria de casos (Chroma en tmp, embeddings falsos) y manual de reglas (JSON en tmp)."""

import json
import math
from types import SimpleNamespace

import chromadb
import pytest

from src.memory import casos, reglas
from src.rag import chroma_client

# Vocabulario -> eje del vector; textos con el mismo tema dan vectores parecidos
_EJES = ["ohm", "circuito", "energia", "palanca", "seguridad"]


class EmbeddingsFalsos:
    def embed_query(self, texto: str) -> list[float]:
        t = texto.lower()
        v = [float(t.count(p)) for p in _EJES] + [0.01]
        n = math.sqrt(sum(x * x for x in v))
        return [x / n for x in v]


@pytest.fixture
def chroma_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(chroma_client, "_client", chromadb.PersistentClient(path=str(tmp_path / "c")))
    monkeypatch.setattr(chroma_client, "active_embedding_model", lambda: "fake")
    monkeypatch.setattr(casos, "get_embeddings", lambda: EmbeddingsFalsos())
    monkeypatch.setattr(casos, "UMBRAL_MEMORIA_CASOS", 0.75)


def test_recordar_vacio(chroma_tmp):
    assert casos.recordar(1, "examen de ohm") == []


def test_archivar_y_recordar_parecido(chroma_tmp):
    casos.archivar(1, "Examen de la ley de Ohm", "EXAMEN OHM")
    casos.archivar(1, "Examen de palancas", "EXAMEN PALANCAS")
    res = casos.recordar(1, "Genera un examen sobre Ohm")
    assert len(res) == 1
    assert res[0].startswith("Petición: Examen de la ley de Ohm")
    assert "EXAMEN OHM" in res[0]


def test_umbral_descarta_lo_poco_parecido(chroma_tmp, monkeypatch):
    casos.archivar(1, "ohm circuito", "MIXTO")
    # coseno("ohm", "ohm circuito") ~ 0.707 < 0.75
    assert casos.recordar(1, "ohm") == []
    monkeypatch.setattr(casos, "UMBRAL_MEMORIA_CASOS", 0.7)
    assert len(casos.recordar(1, "ohm")) == 1


def test_recordar_aislado_por_usuario(chroma_tmp):
    casos.archivar(1, "examen ohm", "DEL 1")
    casos.archivar(2, "examen ohm", "DEL 2")
    res = casos.recordar(2, "ohm")
    assert len(res) == 1 and "DEL 2" in res[0]
    assert casos.recordar(3, "ohm") == []


def test_recordar_respeta_k(chroma_tmp):
    for i in range(4):
        casos.archivar(1, f"ohm {i}", f"C{i}")
    assert len(casos.recordar(1, "ohm", k=2)) == 2
    assert len(casos.recordar(1, "ohm", k=10)) == 4


def test_archivar_trunca_contenido(chroma_tmp):
    casos.archivar(1, "ohm", "x" * 5000)
    (res,) = casos.recordar(1, "ohm")
    assert res.count("x") == casos.MAX_CHARS_CASO


def test_memoria_tolera_fallos(monkeypatch):
    def _roto(_):
        raise RuntimeError("chroma caído")

    monkeypatch.setattr(casos, "coleccion_vectores", _roto)
    casos.archivar(1, "p", "c")  # no lanza
    assert casos.recordar(1, "p") == []


# --- Manual de reglas ----------------------------------------------------------


@pytest.fixture
def manual_tmp(tmp_path, monkeypatch):
    ruta = tmp_path / "sub" / "reglas.json"
    monkeypatch.setattr(reglas, "RUTA_REGLAS", ruta)
    modelo = {"actual": "modelo-a"}
    monkeypatch.setattr(reglas, "get_selection", lambda: SimpleNamespace(llm_model=modelo["actual"]))
    return ruta, modelo


def test_cargar_sin_archivo(manual_tmp):
    assert reglas.cargar("exam_generator") == []


def test_guardar_y_cargar(manual_tmp):
    ruta, _ = manual_tmp
    e = reglas.guardar("exam_generator", ["Cita las rúbricas."], intentos=3)
    assert e["version"] == 1 and e["modelo"] == "modelo-a" and e["intentos"] == 3
    assert reglas.cargar("exam_generator") == ["Cita las rúbricas."]
    assert reglas.cargar("rubric") == []
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    assert set(datos) == {"exam_generator"}


def test_guardar_incrementa_version_y_conserva_otros(manual_tmp):
    reglas.guardar("exam_generator", ["r1"])
    reglas.guardar("rubric", ["rr"])
    e = reglas.guardar("exam_generator", ["r2"])
    assert e["version"] == 2
    assert reglas.cargar("exam_generator") == ["r2"]
    assert reglas.cargar("rubric") == ["rr"]


def test_reglas_no_se_usan_con_otro_modelo(manual_tmp):
    _, modelo = manual_tmp
    reglas.guardar("exam_generator", ["solo para A"])
    modelo["actual"] = "modelo-b"
    assert reglas.cargar("exam_generator") == []
    modelo["actual"] = "modelo-a"
    assert reglas.cargar("exam_generator") == ["solo para A"]


def test_guardar_acentos_utf8(manual_tmp):
    ruta, _ = manual_tmp
    reglas.guardar("exam_generator", ["Incluye una pregunta de seguridad eléctrica."])
    assert "eléctrica" in ruta.read_text(encoding="utf-8")


def test_manual_corrupto_se_ignora(manual_tmp, caplog):
    ruta, _ = manual_tmp
    ruta.parent.mkdir(parents=True)
    ruta.write_text("{no es json", encoding="utf-8")
    with caplog.at_level("WARNING", logger="orquestacion.memoria"):
        assert reglas.cargar("exam_generator") == []
    assert "ilegible" in caplog.text
    # guardar sobre un manual corrupto lo reescribe desde cero
    assert reglas.guardar("exam_generator", ["r"])["version"] == 1
    assert reglas.cargar("exam_generator") == ["r"]
