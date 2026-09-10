"""Tests del validador AST del SQL Agent.

No requiere LLM ni BD real: `validar_query` solo parsea texto SQL con
sqlglot, así que estos tests corren siempre.
"""

import pytest

from src.sql_agent.sql_validator import validar_query

TABLAS = {"alumnos", "notas"}


@pytest.mark.parametrize(
    "query",
    [
        "SELECT * FROM alumnos LIMIT 5",
        "SELECT nombre FROM alumnos WHERE id = 1",
        "SELECT id FROM alumnos UNION SELECT id FROM notas",
        "WITH t AS (SELECT * FROM alumnos) SELECT * FROM t",
        "select COUNT(*) from alumnos",
    ],
)
def test_select_valido_pasa(query):
    resultado = validar_query(query, TABLAS)
    assert resultado.valido, resultado.error


@pytest.mark.parametrize(
    "query",
    [
        "DROP TABLE alumnos",
        "DELETE FROM alumnos",
        "UPDATE alumnos SET nombre = 'x'",
        "TRUNCATE TABLE alumnos",
        "CREATE TABLE x (id int)",
        "ALTER TABLE alumnos ADD COLUMN x int",
        "INSERT INTO alumnos (nombre) VALUES ('x')",
    ],
)
def test_dml_ddl_se_rechaza(query):
    resultado = validar_query(query, TABLAS)
    assert not resultado.valido


def test_multiples_statements_se_rechaza():
    resultado = validar_query("SELECT * FROM alumnos; DROP TABLE alumnos", TABLAS)
    assert not resultado.valido


def test_ddl_ofuscado_con_comentarios_y_mayusculas_se_rechaza():
    resultado = validar_query("/*x*/dRoP/**/table alumnos", TABLAS)
    assert not resultado.valido


def test_dml_anidado_en_cte_se_rechaza():
    resultado = validar_query(
        "WITH cte AS (DELETE FROM alumnos RETURNING *) SELECT * FROM cte", TABLAS
    )
    assert not resultado.valido


@pytest.mark.parametrize(
    "query",
    [
        "SELECT * FROM information_schema.tables",
        "SELECT * FROM mysql.user",
        "SELECT * FROM otra_bd.alumnos",
    ],
)
def test_tabla_calificada_con_schema_se_rechaza(query):
    resultado = validar_query(query, TABLAS)
    assert not resultado.valido


def test_tabla_fuera_de_scope_se_rechaza():
    resultado = validar_query("SELECT * FROM otra_tabla_no_permitida", TABLAS)
    assert not resultado.valido


@pytest.mark.parametrize("query", ["", "   ", "esto no es sql", "SELECT FROM WHERE"])
def test_query_vacia_o_invalida_se_rechaza(query):
    resultado = validar_query(query, TABLAS)
    assert not resultado.valido


def test_resultado_valido_expone_tablas_referenciadas():
    resultado = validar_query("SELECT a.id FROM alumnos a JOIN notas n ON n.alumno_id = a.id", TABLAS)
    assert resultado.valido
    assert set(resultado.tablas) == {"alumnos", "notas"}
