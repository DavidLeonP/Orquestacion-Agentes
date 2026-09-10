"""Ejecución "trust no one" del SQL generado por el agente.

`db_query_tool` (src/sql_agent/tools.py) es el único punto que invoca esto,
pero esta función no asume que su llamador ya validó correctamente: vuelve
a correr el validador AST (sql_validator.py) sobre su propia lista de tablas
permitidas, consultada en el momento, antes de tocar la BD. `tenant` es un
argumento obligatorio — no se infiere ni se reutiliza uno por defecto —
precisamente para que un bug de wiring no pueda ejecutar SQL sin que quede
explícito a qué docente/tenant pertenece.
"""

from __future__ import annotations

from langchain_community.utilities import SQLDatabase

from src.sql_agent.sql_validator import validar_query


def ejecutar_sql_validado(tenant: str, db: SQLDatabase, query: str) -> str:
    """Revalida `query` de forma independiente y la ejecuta si es válida."""
    if not tenant:
        raise ValueError("tenant es obligatorio: nunca se ejecuta SQL sin un dueño conocido.")

    resultado = validar_query(query, set(db.get_usable_table_names()))
    if not resultado.valido:
        return f"Error: {resultado.error}"

    salida = db.run_no_throw(query)
    if not salida:
        return "Error: Query failed. Please rewrite your query and try again."
    return salida
