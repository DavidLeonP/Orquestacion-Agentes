"""Índice vectorial de la KB en Chroma (kb_vectores) y fusión RRF/BM25, sin red."""

from types import SimpleNamespace

import chromadb
import pytest
from rank_bm25 import BM25Okapi

from src.rag import chroma_client, kb_vectores
from src.rag.rrf import RRF_K, fusion_rrf, ranking_bm25, tokenizar


@pytest.fixture
def chroma_tmp(tmp_path, monkeypatch):
    cliente = chromadb.PersistentClient(path=str(tmp_path / "chroma"))
    monkeypatch.setattr(chroma_client, "_client", cliente)
    monkeypatch.setattr(chroma_client, "active_embedding_model", lambda: "fake-embed/v1")
    return cliente


def _chunk(user_id, uid, indice="apuntes", document_id=1):
    return SimpleNamespace(user_id=user_id, chunk_uid=uid, indice=indice, document_id=document_id)


def _cargar_kb():
    chunks = [
        _chunk(1, "a", document_id=10),
        _chunk(1, "b", document_id=10),
        _chunk(1, "c", document_id=11),
        _chunk(1, "x", indice="examenes", document_id=12),
        _chunk(2, "a", document_id=20),  # mismo chunk_uid que el del usuario 1
    ]
    vectores = [
        [1.0, 0.0, 0.0],
        [0.9, 0.1, 0.0],
        [0.0, 1.0, 0.0],
        [1.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
    ]
    kb_vectores.upsert(chunks, vectores)


def test_nombre_coleccion_saneado_y_coseno(chroma_tmp):
    col = chroma_client.coleccion_vectores("kb")
    assert col.name == "kb_fake-embed_v1"
    assert col.metadata.get("hnsw:space") == "cosine"


def test_filtro_uno_y_varios_campos():
    assert chroma_client.filtro(user_id=1) == {"user_id": 1}
    assert chroma_client.filtro(user_id=1, indice="a") == {
        "$and": [{"user_id": 1}, {"indice": "a"}]
    }


def test_id_vector_incluye_usuario():
    assert chroma_client.id_vector(3, "abc") == "3:abc"


def test_buscar_ordena_y_filtra_por_usuario_e_indice(chroma_tmp):
    _cargar_kb()
    assert kb_vectores.buscar(1, "apuntes", [1.0, 0.0, 0.0], 3) == ["a", "b", "c"]
    assert kb_vectores.buscar(1, "apuntes", [0.0, 1.0, 0.0], 1) == ["c"]
    # Aislamiento: el usuario 2 solo ve su chunk aunque comparta chunk_uid
    assert kb_vectores.buscar(2, "apuntes", [1.0, 0.0, 0.0], 5) == ["a"]
    assert kb_vectores.buscar(1, "examenes", [1.0, 0.0, 0.0], 5) == ["x"]
    # Chunks con mismo chunk_uid de distinto usuario no se pisan
    assert chroma_tmp.get_collection("kb_fake-embed_v1").count() == 5


def test_buscar_k_mayor_que_documentos(chroma_tmp):
    _cargar_kb()
    assert sorted(kb_vectores.buscar(1, "apuntes", [1.0, 0.0, 0.0], 50)) == ["a", "b", "c"]


def test_buscar_sin_documentos_del_usuario(chroma_tmp):
    _cargar_kb()
    assert kb_vectores.buscar(99, "apuntes", [1.0, 0.0, 0.0], 3) == []


def test_upsert_es_idempotente_y_actualiza(chroma_tmp):
    _cargar_kb()
    kb_vectores.upsert([_chunk(1, "c", document_id=11)], [[1.0, 0.0, 0.0]])
    assert chroma_tmp.get_collection("kb_fake-embed_v1").count() == 5
    # c ya no es el vecino de [0,1,0]: ahora lo es b (el único con componente y)
    assert kb_vectores.buscar(1, "apuntes", [0.0, 1.0, 0.0], 1) == ["b"]


def test_upsert_vacio_no_falla(chroma_tmp):
    assert kb_vectores.upsert([], []) == "kb_fake-embed_v1"


def test_estado_cuenta_por_usuario_e_indice(chroma_tmp):
    _cargar_kb()
    info = kb_vectores.estado(1, "apuntes")
    assert info["ok"] is True
    assert info["coleccion"] == "kb_fake-embed_v1"
    assert info["total_coleccion"] == 5
    assert info["vectores_usuario"] == 4
    assert info["vectores_indice"] == 3
    assert {fila["document_id"]: fila["vectores"] for fila in info["por_documento"]} == {10: 2, 11: 1}


def test_borrar_documento(chroma_tmp):
    _cargar_kb()
    kb_vectores.borrar_documento(10)
    assert kb_vectores.buscar(1, "apuntes", [1.0, 0.0, 0.0], 5) == ["c"]
    # El resto de usuarios/documentos sigue intacto
    assert kb_vectores.buscar(2, "apuntes", [1.0, 0.0, 0.0], 5) == ["a"]
    kb_vectores.borrar_documento(12345)  # inexistente: no lanza


def test_borrar_documento_traga_errores(monkeypatch):
    def _roto():
        raise RuntimeError("chroma caído")

    monkeypatch.setattr(kb_vectores, "_kb", _roto)
    kb_vectores.borrar_documento(1)  # solo log, no propaga


def test_sincronizar_sin_faltantes_no_consulta_mysql(chroma_tmp):
    _cargar_kb()

    class DbQueNoSeUsa:
        def query(self, *a, **k):
            raise AssertionError("no debía consultar MySQL")

    assert kb_vectores.sincronizar(DbQueNoSeUsa(), 1, "apuntes", ["a", "b", "c"]) == 0
    assert kb_vectores.sincronizar(DbQueNoSeUsa(), 1, "apuntes", []) == 0


def test_sincronizar_copia_los_que_faltan(chroma_tmp, monkeypatch):
    _cargar_kb()
    monkeypatch.setattr(kb_vectores, "active_embedding_model", lambda: "fake-embed/v1")
    nuevo = _chunk(1, "d", document_id=13)

    class Query:
        def __init__(self):
            self.llamadas = []

        def join(self, *a, **k):
            return self

        def filter(self, *a, **k):
            self.llamadas.append(a)
            return self

        def all(self):
            return [(nuevo, [0.0, 0.0, 1.0])]

    q = Query()
    db = SimpleNamespace(query=lambda *a, **k: q)
    assert kb_vectores.sincronizar(db, 1, "apuntes", ["a", "d"]) == 1
    assert kb_vectores.buscar(1, "apuntes", [0.0, 0.0, 1.0], 1) == ["d"]


# --- RRF / BM25 ---------------------------------------------------------------


def test_tokenizar():
    assert tokenizar("Ley de Ohm: V=I·R, ¡Circuito!") == ["ley", "de", "ohm", "v", "i", "r", "circuito"]


def test_fusion_rrf_premia_consenso():
    r1 = ["a", "b", "c"]
    r2 = ["b", "c", "a"]
    r3 = ["b", "d"]
    assert fusion_rrf([r1, r2, r3], 2) == ["b", "a"]


def test_fusion_rrf_puntuacion_y_k():
    # Un único ranking conserva el orden; k recorta
    assert fusion_rrf([["x", "y", "z"]], 2) == ["x", "y"]
    assert fusion_rrf([["x"]], 10) == ["x"]
    assert fusion_rrf([], 5) == []
    assert fusion_rrf([[], []], 5) == []
    # Empate exacto (a en pos 1 de uno, b en pos 1 del otro) -> ambos presentes
    assert set(fusion_rrf([["a"], ["b"]], 2)) == {"a", "b"}
    assert RRF_K == 60


def test_ranking_bm25():
    textos = ["la ley de ohm relaciona tension", "circuito en serie", "resistencias en paralelo ohm ohm"]
    ids = ["t1", "t2", "t3"]
    bm25 = BM25Okapi([tokenizar(t) for t in textos])
    ranking = ranking_bm25(bm25, ids, "circuito serie", 3)
    assert ranking[0] == "t2"
    assert len(ranking) == 3
    assert ranking_bm25(bm25, ids, "circuito", 1) == ["t2"]
    assert len(ranking_bm25(bm25, ids, "x", 10)) == 3


# Regresión (chroma_client.py): antes se truncaba a 63 caracteres sin limpiar el
# final y Chroma rechazaba "casos_<modelo largo>-" o "kb_modelo_".
@pytest.mark.parametrize(
    "modelo, prefijo",
    [
        ("sentence-transformers/paraphrase-multilingual-mpnet-base-v2", "casos"),
        ("modelo:", "kb"),
        ("org/modelo.v2.", "casos"),
    ],
)
def test_nombre_coleccion_valido_con_modelos_raros(chroma_tmp, monkeypatch, modelo, prefijo):
    monkeypatch.setattr(chroma_client, "active_embedding_model", lambda: modelo)
    nombre = chroma_client.coleccion_vectores(prefijo).name
    assert nombre[0].isalnum() and nombre[-1].isalnum()


@pytest.mark.parametrize("modelo", ["text-embedding-3-small", "BAAI/bge-m3", "nomic-embed-text:latest"])
@pytest.mark.parametrize("prefijo", ["kb", "casos"])
def test_nombre_coleccion_perfiles_por_defecto(chroma_tmp, monkeypatch, modelo, prefijo):
    monkeypatch.setattr(chroma_client, "active_embedding_model", lambda: modelo)
    assert chroma_client.coleccion_vectores(prefijo).name.startswith(prefijo + "_")


# --- RetrieverHibridoMySQL con backend chroma y fallbacks -----------------------

from src.rag import mysql_store  # noqa: E402


class _Emb:
    def __init__(self, texto, model="fake-embed/v1"):
        self.embedding = [1.0, 0.0, 0.0] if "ohm" in texto else [0.0, 1.0, 0.0]
        self.model = model


def _filas():
    textos = {"a": "la ley de ohm", "b": "circuito en serie", "c": "palancas y poleas"}
    return [
        SimpleNamespace(user_id=1, indice="apuntes", document_id=1, chunk_uid=u, texto=t,
                        metadatos={"fuente": f"{u}.txt"}, embedding=_Emb(t), position=i)
        for i, (u, t) in enumerate(textos.items())
    ]


class _Query:
    def __init__(self, filas):
        self.filas = filas

    def filter(self, *a, **k):
        return self

    def options(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def all(self):
        return self.filas


class _Db:
    def __init__(self, filas):
        self.filas = filas
        self.consultas = 0

    def query(self, *a, **k):
        self.consultas += 1
        return _Query(self.filas)

    def rollback(self):
        self.rollbacks = getattr(self, "rollbacks", 0) + 1

    def close(self):
        pass


class _Embedder:
    def embed_query(self, texto):
        return [1.0, 0.0, 0.0] if "ohm" in texto.lower() else [0.0, 1.0, 0.0]


@pytest.fixture
def retriever_env(monkeypatch):
    monkeypatch.setattr(mysql_store, "get_embeddings", lambda: _Embedder())
    monkeypatch.setattr(mysql_store, "active_embedding_model", lambda: "fake-embed/v1")
    monkeypatch.setattr(mysql_store, "VECTOR_BACKEND", "chroma")


def test_retriever_sincronizar_falla_cae_a_mysql_una_vez(retriever_env, monkeypatch):
    llamadas = []

    def _falla(*a, **k):
        llamadas.append(1)
        raise RuntimeError("chroma caído")

    monkeypatch.setattr(mysql_store.kb_vectores, "sincronizar", _falla)
    db = _Db(_filas())
    r = mysql_store.RetrieverHibridoMySQL(1, "apuntes", db=db)
    assert r.backend == "mysql"
    assert llamadas == [1] and db.consultas == 2  # recarga una sola vez, sin recursión
    assert db.rollbacks == 1  # limpia la transacción fallida antes de recargar
    assert r.buscar("ley de ohm", k=1)[0]["id"] == "a"
    assert set(r._embeddings) == {"a", "b", "c"}


def test_retriever_buscar_chroma_falla_queda_bm25(retriever_env, monkeypatch):
    monkeypatch.setattr(mysql_store.kb_vectores, "sincronizar", lambda *a, **k: 0)

    def _falla(*a, **k):
        raise RuntimeError("query rota")

    monkeypatch.setattr(mysql_store.kb_vectores, "buscar", _falla)
    r = mysql_store.RetrieverHibridoMySQL(1, "apuntes", db=_Db(_filas()))
    assert r.backend == "chroma"
    assert r.buscar("poleas", k=1)[0]["id"] == "c"


def test_retriever_descarta_vectores_huerfanos(retriever_env, monkeypatch):
    monkeypatch.setattr(mysql_store.kb_vectores, "sincronizar", lambda *a, **k: 0)
    monkeypatch.setattr(mysql_store.kb_vectores, "buscar", lambda *a, **k: ["huerfano", "b"])
    r = mysql_store.RetrieverHibridoMySQL(1, "apuntes", db=_Db(_filas()))
    ids = [c["id"] for c in r.buscar("circuito", k=4)]
    assert "huerfano" not in ids and ids[0] == "b"


def test_retriever_chroma_real_extremo_a_extremo(retriever_env, chroma_tmp):
    filas = _filas()
    kb_vectores.upsert(filas, [f.embedding.embedding for f in filas])
    r = mysql_store.RetrieverHibridoMySQL(1, "apuntes", db=_Db(filas))
    assert r.backend == "chroma"
    assert r.buscar("ohm", k=1)[0]["metadatos"]["fuente"] == "a.txt"


def test_retriever_sin_chunks(retriever_env, monkeypatch):
    monkeypatch.setattr(mysql_store.kb_vectores, "sincronizar", lambda *a, **k: 0)
    assert mysql_store.RetrieverHibridoMySQL(1, "apuntes", db=_Db([])).buscar("x") == []


def _db_sincronizar(filas):
    class Q:
        def join(self, *a, **k):
            return self

        def filter(self, *a, **k):
            return self

        def all(self):
            return filas

    consultas = []

    def query(*a, **k):
        consultas.append(a)
        return Q()

    return SimpleNamespace(query=query, consultas=consultas)


def test_sincronizar_forzar_reescribe_todo(chroma_tmp, monkeypatch):
    _cargar_kb()
    monkeypatch.setattr(kb_vectores, "active_embedding_model", lambda: "fake-embed/v1")
    nuevo_a = _chunk(1, "a", document_id=10)
    db = _db_sincronizar([(nuevo_a, [0.0, 0.0, 1.0])])
    assert kb_vectores.sincronizar(db, 1, "apuntes", ["a", "b", "c"]) == 0  # nada falta
    assert db.consultas == []
    assert kb_vectores.sincronizar(db, 1, "apuntes", ["a", "b", "c"], forzar=True) == 1
    assert kb_vectores.buscar(1, "apuntes", [0.0, 0.0, 1.0], 1) == ["a"]


def test_sincronizar_sin_embeddings_del_modelo_avisa_y_devuelve_0(chroma_tmp, monkeypatch, caplog):
    monkeypatch.setattr(kb_vectores, "active_embedding_model", lambda: "fake-embed/v1")
    with caplog.at_level("WARNING", logger="orquestacion.rag"):
        assert kb_vectores.sincronizar(_db_sincronizar([]), 1, "apuntes", ["z"]) == 0
    assert "Sin embeddings" in caplog.text


def test_hybrid_legado_eliminado():
    import importlib.util

    assert importlib.util.find_spec("src.rag.hybrid") is None


# --- RetrieverHibridoMySQL libera la sesión tras cargar ----------------------------


class _DbCierre(_Db):
    def __init__(self, filas, falla=False):
        super().__init__(filas)
        self.cierres = 0
        self.falla = falla

    def query(self, *a, **k):
        if self.falla:
            raise RuntimeError("MySQL caído")
        return super().query(*a, **k)

    def close(self):
        self.cierres += 1


def test_retriever_sin_db_cierra_su_sesion_una_vez(retriever_env, monkeypatch):
    db = _DbCierre(_filas())
    monkeypatch.setattr(mysql_store, "SessionLocal", lambda: db)
    monkeypatch.setattr(mysql_store, "VECTOR_BACKEND", "mysql")
    r = mysql_store.RetrieverHibridoMySQL(1, "apuntes")
    assert db.cierres == 1
    # buscar() no vuelve a tocar MySQL tras el close
    db.falla = True
    assert r.buscar("ley de ohm", k=1)[0]["id"] == "a"
    assert db.cierres == 1


def test_retriever_no_cierra_la_sesion_del_llamador(retriever_env, monkeypatch):
    monkeypatch.setattr(mysql_store.kb_vectores, "sincronizar", lambda *a, **k: 0)
    monkeypatch.setattr(mysql_store.kb_vectores, "buscar", lambda *a, **k: ["c"])
    db = _DbCierre(_filas())
    r = mysql_store.RetrieverHibridoMySQL(1, "apuntes", db=db)
    assert db.cierres == 0
    db.falla = True
    assert r.buscar("poleas", k=1)[0]["id"] == "c"  # backend chroma tras cargar


def test_retriever_fallback_mysql_ocurre_antes_del_close(retriever_env, monkeypatch):
    def _falla(*a, **k):
        raise RuntimeError("chroma caído")

    monkeypatch.setattr(mysql_store.kb_vectores, "sincronizar", _falla)
    db = _DbCierre(_filas())
    monkeypatch.setattr(mysql_store, "SessionLocal", lambda: db)
    r = mysql_store.RetrieverHibridoMySQL(1, "apuntes")
    assert r.backend == "mysql" and db.consultas == 2 and db.cierres == 1
    db.falla = True
    assert r.buscar("ohm", k=1)[0]["id"] == "a"


# Regresión (mysql_store.py, __init__): antes la sesión propia quedaba abierta si _cargar lanzaba.
def test_retriever_cierra_la_sesion_aunque_cargar_falle(retriever_env, monkeypatch):
    db = _DbCierre(_filas(), falla=True)
    monkeypatch.setattr(mysql_store, "SessionLocal", lambda: db)
    with pytest.raises(RuntimeError):
        mysql_store.RetrieverHibridoMySQL(1, "apuntes")
    assert db.cierres == 1
