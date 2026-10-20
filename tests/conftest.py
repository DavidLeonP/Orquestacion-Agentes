"""Configuración común de tests: sin red.

1. Sin trazas a LangSmith: src/config.py hace load_dotenv() y el .env local activa
   LANGCHAIN_TRACING_V2. load_dotenv no sobrescribe variables ya definidas, así
   que basta con fijarlas aquí, antes de que se importe src.
2. Fixture autouse que bloquea socket.connect a hosts que no sean localhost, para
   que ningún test se cuelgue llamando a OpenAI, vLLM o MySQL. Los tests que sí
   usan red (test_sql_agent_api, test_sql_agent_graph, test_pipeline_api) se
   excluyen con --ignore.
"""

import os
import socket

import pytest

for _var in ("LANGCHAIN_TRACING_V2", "LANGCHAIN_TRACING", "LANGSMITH_TRACING", "LANGSMITH_TRACING_V2"):
    os.environ[_var] = "false"

_LOCALES = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
_connect_original = socket.socket.connect
_connect_ex_original = socket.socket.connect_ex


def _es_local(direccion) -> bool:
    if isinstance(direccion, (str, bytes)):  # socket AF_UNIX
        return True
    host = direccion[0] if isinstance(direccion, tuple) and direccion else ""
    return host in _LOCALES or str(host).startswith("127.")


class RedBloqueada(RuntimeError):
    pass


def _connect_bloqueado(self, direccion):
    if not _es_local(direccion):
        raise RedBloqueada(f"Test sin red: conexión bloqueada a {direccion!r}")
    return _connect_original(self, direccion)


def _connect_ex_bloqueado(self, direccion):
    if not _es_local(direccion):
        raise RedBloqueada(f"Test sin red: conexión bloqueada a {direccion!r}")
    return _connect_ex_original(self, direccion)


@pytest.fixture(autouse=True)
def _sin_red(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", _connect_bloqueado)
    monkeypatch.setattr(socket.socket, "connect_ex", _connect_ex_bloqueado)
    yield
