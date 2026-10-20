"""Clientes sin JWT (CLI y API legado): usuario en contexto e ingesta de data/ (sin red ni MySQL)."""

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from pypdf import PdfWriter

from src import contexto_usuario as cu
from src.ingestion import carpeta_data
from src.memory import mysql_store as mem
from src.rag import context as rag_context


def _uid_memoria():
    return mem._memory_user_id.get()


# --- contexto_usuario ------------------------------------------------------------


def test_contexto_usuario_fija_y_restaura():
    assert rag_context.rag_user_id_actual() is None and _uid_memoria() is None
    with cu.contexto_usuario(3) as uid:
        assert uid == 3
        assert rag_context.get_rag_user_id() == 3 and mem._uid() == 3
        with cu.contexto_usuario(4):
            assert rag_context.get_rag_user_id() == 4 and mem._uid() == 4
        assert rag_context.get_rag_user_id() == 3 and mem._uid() == 3
    assert rag_context.rag_user_id_actual() is None and _uid_memoria() is None


def test_contexto_usuario_restaura_con_excepcion():
    with pytest.raises(ValueError):
        with cu.contexto_usuario(9):
            raise ValueError("fallo dentro")
    assert rag_context.rag_user_id_actual() is None and _uid_memoria() is None


# --- resolver_usuario_legado -----------------------------------------------------


class _DbUsuarios:
    def __init__(self, existente=None):
        self.existente = existente
        self.añadidos = []
        self.cerrada = False

    def query(self, *a):
        return self

    def filter(self, *a):
        return self

    def first(self):
        return self.existente

    def add(self, obj):
        self.añadidos.append(obj)

    def commit(self):
        pass

    def refresh(self, obj):
        obj.id = 77

    def close(self):
        self.cerrada = True


def test_resolver_respeta_legacy_api_user_id(monkeypatch):
    monkeypatch.setenv("LEGACY_API_USER_ID", "12")

    def _no_db():
        raise AssertionError("no debía abrir sesión")

    monkeypatch.setattr(cu, "SessionLocal", _no_db)
    assert cu.resolver_usuario_legado() == 12


def test_resolver_por_email_existente(monkeypatch):
    monkeypatch.delenv("LEGACY_API_USER_ID", raising=False)
    monkeypatch.setenv("LEGACY_API_USER_EMAIL", "Profe@X.local")
    db = _DbUsuarios(existente=SimpleNamespace(id=5))
    monkeypatch.setattr(cu, "SessionLocal", lambda: db)
    assert cu.resolver_usuario_legado() == 5
    assert db.añadidos == [] and db.cerrada


def test_resolver_crea_docente_si_falta(monkeypatch):
    monkeypatch.delenv("LEGACY_API_USER_ID", raising=False)
    monkeypatch.setenv("LEGACY_API_USER_EMAIL", "Nuevo@X.local")
    import src.api.security as security

    monkeypatch.setattr(security, "hash_password", lambda p: "hash")
    db = _DbUsuarios()
    monkeypatch.setattr(cu, "SessionLocal", lambda: db)
    assert cu.resolver_usuario_legado(crear=True) == 77
    (u,) = db.añadidos
    assert u.email == "nuevo@x.local" and u.rol == "docente" and db.cerrada


def test_resolver_sin_crear_aborta_si_falta(monkeypatch):
    # CLI: no crea usuarios (no pisa el alta normal con otra contraseña)
    monkeypatch.delenv("LEGACY_API_USER_ID", raising=False)
    monkeypatch.setenv("LEGACY_API_USER_EMAIL", "nadie@x.local")
    db = _DbUsuarios()
    monkeypatch.setattr(cu, "SessionLocal", lambda: db)
    with pytest.raises(SystemExit, match="nadie@x.local"):
        cu.resolver_usuario_legado()
    assert db.añadidos == [] and db.cerrada


# --- main._ejecutar ----------------------------------------------------------------


class _Interrupt:
    def __init__(self, value):
        self.value = value


class GrafoFalso:
    """Sus 'tools' leen el usuario del contexto, como las RAG reales."""

    def __init__(self, con_hitl):
        self.con_hitl = con_hitl
        self.vistos = []
        self.entradas = []

    def stream(self, entrada, config=None, stream_mode=None):
        self.entradas.append(entrada)
        self.vistos.append((rag_context.get_rag_user_id(), mem._uid()))
        if self.con_hitl and isinstance(entrada, dict):
            yield {"router": {"agente_destino": "exam_generator"}}
            yield {"__interrupt__": (_Interrupt({"borrador": "BORRADOR", "veredicto": {"aprobado": True}}),)}
        else:
            yield {"finalizar": {"respuesta_final": "RESPUESTA. Fuentes consultadas: a.txt"}}


@pytest.fixture
def main_mod(monkeypatch):
    import main

    import src.orchestrator.graph as grafo_mod

    monkeypatch.setattr(main, "configurar_observabilidad", lambda: None)
    monkeypatch.setattr(main, "TrazasSolicitud", lambda *a, **k: nullcontext())
    monkeypatch.setattr(main, "registrar_evento", lambda *a, **k: None)
    llamadas = []
    monkeypatch.setattr(cu, "resolver_usuario_legado", lambda **k: llamadas.append(k) or 31)
    monkeypatch.setattr(main, "_resolver_llamadas", llamadas, raising=False)
    return main, grafo_mod


@pytest.mark.parametrize("con_hitl", [False, True])
def test_main_ejecutar_fija_usuario_para_las_tools(main_mod, monkeypatch, capsys, con_hitl):
    main, grafo_mod = main_mod
    grafo = GrafoFalso(con_hitl)
    monkeypatch.setattr(grafo_mod, "construir_grafo", lambda *a, **k: grafo)
    monkeypatch.setattr("builtins.input", lambda *a: "si")
    main._ejecutar("Genera un examen", "docente")
    salida = capsys.readouterr().out
    assert "RESPUESTA" in salida
    assert grafo.vistos == [(31, 31)] * (2 if con_hitl else 1)
    if con_hitl:
        assert "BORRADOR" in salida and "VEREDICTO: APROBADO" in salida
        assert type(grafo.entradas[1]).__name__ == "Command" and grafo.entradas[1].resume == "si"
    assert rag_context.rag_user_id_actual() is None and _uid_memoria() is None
    assert main._resolver_llamadas == [{}]  # el CLI no pide crear el usuario


# --- sincronizar_carpeta_data ----------------------------------------------------


class _DbDocs:
    def __init__(self, existentes):
        self.existentes = [SimpleNamespace(indice=i, filename=f) for i, f in existentes]
        self.añadidos = []
        self.commits = 0
        self.cerrada = False

    def query(self, *a):
        return self

    def filter(self, *a):
        return iter(self.existentes)

    def add(self, obj):
        self.añadidos.append(obj)

    def commit(self):
        self.commits += 1

    def close(self):
        self.cerrada = True


@pytest.fixture
def carpeta(tmp_path, monkeypatch):
    indices = {n: tmp_path / n for n in ("apuntes", "examenes", "rubricas", "curriculo")}
    indices["apuntes"].mkdir()
    indices["rubricas"].mkdir()
    (indices["apuntes"] / "viejo.txt").write_text("ya estaba", encoding="utf-8")
    (indices["apuntes"] / "ohm.md").write_text("# Ley de Ohm", encoding="utf-8")
    (indices["apuntes"] / "ignorado.docx").write_bytes(b"x")
    w = PdfWriter()
    w.add_blank_page(width=100, height=100)
    with open(indices["rubricas"] / "rubrica.pdf", "wb") as fh:
        w.write(fh)
    (indices["rubricas"] / "viejo.txt").write_text("mismo nombre, otro índice", encoding="utf-8")
    monkeypatch.setattr(carpeta_data, "INDICES", indices)
    return indices


def test_sincronizar_crea_solo_los_que_faltan(carpeta, monkeypatch):
    db = _DbDocs([("apuntes", "viejo.txt")])
    monkeypatch.setattr(carpeta_data, "SessionLocal", lambda: db)
    llamadas = []
    monkeypatch.setattr(carpeta_data, "ingest_pendientes",
                        lambda d, uid: llamadas.append(uid) or {"procesados": 3, "detalle": []})
    res = carpeta_data.sincronizar_carpeta_data(8)
    creados = sorted((d.indice, d.filename) for d in db.añadidos)
    assert creados == [("apuntes", "ohm.md"), ("rubricas", "rubrica.pdf"), ("rubricas", "viejo.txt")]
    assert res == {"documentos_nuevos": 3, "ilegibles": [], "procesados": 3, "detalle": []}
    assert llamadas == [8] and db.commits == 1 and db.cerrada
    for d in db.añadidos:
        assert d.user_id == 8 and d.status == "pending" and d.metadatos == {"fuente": d.filename}
    md = next(d for d in db.añadidos if d.filename == "ohm.md")
    assert md.content_text == "# Ley de Ohm"


def test_sincronizar_es_idempotente(carpeta, monkeypatch):
    class DbPersistente(_DbDocs):
        def add(self, obj):
            super().add(obj)
            self.existentes.append(SimpleNamespace(indice=obj.indice, filename=obj.filename))

    db = DbPersistente([])
    monkeypatch.setattr(carpeta_data, "SessionLocal", lambda: db)
    monkeypatch.setattr(carpeta_data, "ingest_pendientes", lambda d, uid: {})
    assert carpeta_data.sincronizar_carpeta_data(8)["documentos_nuevos"] == 4
    assert carpeta_data.sincronizar_carpeta_data(8)["documentos_nuevos"] == 0


def test_sincronizar_sin_nada_nuevo_indexa_igual(carpeta, monkeypatch):
    db = _DbDocs([("apuntes", "viejo.txt"), ("apuntes", "ohm.md"), ("rubricas", "rubrica.pdf"),
                  ("rubricas", "viejo.txt")])
    monkeypatch.setattr(carpeta_data, "SessionLocal", lambda: db)
    monkeypatch.setattr(carpeta_data, "ingest_pendientes", lambda d, uid: {"detalle": []})
    assert carpeta_data.sincronizar_carpeta_data(8)["documentos_nuevos"] == 0
    assert db.añadidos == []


def test_sincronizar_archivo_ilegible_no_frena_al_resto(carpeta, monkeypatch):
    # Un .txt en latin-1 se reporta en "ilegibles"; los demás se crean e indexan
    (carpeta["apuntes"] / "latin1.txt").write_bytes("electricidad básica".encode("latin-1"))
    db = _DbDocs([])
    monkeypatch.setattr(carpeta_data, "SessionLocal", lambda: db)
    monkeypatch.setattr(carpeta_data, "ingest_pendientes", lambda d, uid: {})
    res = carpeta_data.sincronizar_carpeta_data(8)
    assert [i["filename"] for i in res["ilegibles"]] == ["latin1.txt"]
    assert res["documentos_nuevos"] == 4
    assert "latin1.txt" not in {d.filename for d in db.añadidos}
    assert db.commits == 1 and db.cerrada


# --- POST /api/v1/ingestar (API legado) -------------------------------------------


@pytest.fixture
def cliente_legado(monkeypatch):
    from fastapi.testclient import TestClient

    from src import legacy_chat_api

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    llamadas = []
    monkeypatch.setattr(legacy_chat_api, "resolver_usuario_legado", lambda **k: llamadas.append(k) or 21)
    legacy_chat_api._resolver_llamadas = llamadas
    return TestClient(legacy_chat_api.app), legacy_chat_api


def test_ingestar_conserva_claves(cliente_legado, monkeypatch):
    cliente, mod = cliente_legado
    resultado = {
        "documentos_nuevos": 2,
        "detalle": [{"filename": "ohm.md", "chunks": 4}, {"filename": "malo.pdf", "error": "x"}],
    }
    recibidos = []
    monkeypatch.setattr(mod, "sincronizar_carpeta_data", lambda uid: recibidos.append(uid) or resultado)
    r = cliente.post("/api/v1/ingestar")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"status", "documentos_nuevos", "indices", "ingest"}
    assert body["status"] == "ok" and body["documentos_nuevos"] == 2
    assert body["indices"] == {"ohm.md": 4}
    assert body["ingest"] == resultado
    assert recibidos == [21]
    assert mod._resolver_llamadas == [{"crear": True}]  # la API legado sí crea el usuario


def test_ingestar_error_devuelve_500(cliente_legado, monkeypatch):
    cliente, mod = cliente_legado

    def _falla(uid):
        raise RuntimeError("MySQL caído")

    monkeypatch.setattr(mod, "sincronizar_carpeta_data", _falla)
    r = cliente.post("/api/v1/ingestar")
    assert r.status_code == 500 and "MySQL caído" in r.json()["detail"]


def test_ingestar_sin_api_key_503(cliente_legado, monkeypatch):
    cliente, _ = cliente_legado
    monkeypatch.delenv("OPENAI_API_KEY")
    assert cliente.post("/api/v1/ingestar").status_code == 503
