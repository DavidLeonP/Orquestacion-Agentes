"""El fixture de conftest bloquea la red externa y deja pasar localhost."""

import socket

import pytest

from tests.conftest import RedBloqueada


def test_red_externa_bloqueada():
    s = socket.socket()
    try:
        with pytest.raises(RedBloqueada):
            s.connect(("203.0.113.10", 443))  # TEST-NET-3: nunca responde
    finally:
        s.close()


def test_localhost_permitido():
    servidor = socket.socket()
    servidor.bind(("127.0.0.1", 0))
    servidor.listen(1)
    cliente = socket.socket()
    try:
        cliente.connect(servidor.getsockname())
    finally:
        cliente.close()
        servidor.close()


def test_mysql_externo_falla_rapido():
    from sqlalchemy import create_engine, text

    engine = create_engine("mysql+pymysql://u:p@198.51.100.7:3306/db")
    with pytest.raises(Exception):
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
