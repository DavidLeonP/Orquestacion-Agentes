"""Validación estructural (AST) de las consultas que el SQL Agent intenta
ejecutar contra la BD de negocio.

No confía en el prompt ("no hagas DML", ver QUERY_GEN_SYSTEM en prompts.py)
ni en que el usuario de BD sea de solo lectura (recomendado en .env.example,
pero no verificable desde aquí): ambos pueden fallar o estar mal
configurados. Se parsea la consulta con `sqlglot` a un árbol de sintaxis y
se rechaza estructuralmente cualquier cosa que no sea un SELECT de solo
lectura sobre tablas conocidas — no por coincidencia de texto/regex, que se
evade con comentarios, mayúsculas o sentencias anidadas (p. ej. un DELETE
dentro de un CTE con RETURNING).

Este módulo es la primera barrera. El ejecutor (`executor.py`) vuelve a
llamarlo de forma independiente antes de tocar la BD — "trust no one":
nunca asumir que quien invoca ya validó.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp

DIALECTO = "mysql"

_RAICES_PERMITIDAS = (exp.Select, exp.Union, exp.Intersect, exp.Except)

_NODOS_PROHIBIDOS = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Alter,
    exp.Create,
    exp.TruncateTable,
)


@dataclass
class ResultadoValidacion:
    valido: bool
    error: str | None = None
    tablas: list[str] = field(default_factory=list)


def validar_query(query: str, tablas_permitidas: set[str] | list[str]) -> ResultadoValidacion:
    """Valida `query` por AST, no por texto.

    Reglas (todas obligatorias, independientes del prompt):
    - Debe parsear como un único statement.
    - La raíz debe ser SELECT/UNION/INTERSECT/EXCEPT — nada más.
    - Ningún nodo del árbol (tampoco en subqueries/CTEs) puede ser DML/DDL:
      INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE.
    - Ninguna tabla referenciada puede llevar schema/catálogo explícito
      (bloquea `information_schema.x`, `mysql.user`, BDs cruzadas).
    - Toda tabla referenciada (que no sea un alias de CTE definido en la
      misma query) debe estar en `tablas_permitidas`.
    """
    texto = (query or "").strip()
    if not texto:
        return ResultadoValidacion(False, "La consulta está vacía.")

    try:
        statements = [s for s in sqlglot.parse(texto, dialect=DIALECTO) if s is not None]
    except Exception as exc:  # sqlglot.errors.ParseError y similares: fail closed
        return ResultadoValidacion(False, f"No se pudo parsear la consulta SQL: {exc}")

    if len(statements) != 1:
        return ResultadoValidacion(
            False,
            "Solo se permite un único statement SQL por consulta (sin ';' múltiples).",
        )

    raiz = statements[0]

    if not isinstance(raiz, _RAICES_PERMITIDAS):
        return ResultadoValidacion(
            False, f"Solo se permiten consultas SELECT (se recibió {type(raiz).__name__})."
        )

    prohibidos = list(raiz.find_all(_NODOS_PROHIBIDOS))
    if prohibidos:
        nombres = sorted({type(n).__name__ for n in prohibidos})
        return ResultadoValidacion(
            False, f"La consulta contiene operaciones no permitidas: {', '.join(nombres)}."
        )

    permitidas_lower = {t.lower() for t in tablas_permitidas}
    alias_cte = {c.alias.lower() for c in raiz.find_all(exp.CTE) if c.alias}

    tablas: list[str] = []
    for tb in raiz.find_all(exp.Table):
        nombre = tb.name
        if not nombre or nombre.lower() in alias_cte:
            continue
        if tb.db:
            return ResultadoValidacion(
                False,
                f"No se permite calificar tablas con schema/BD ('{tb.db}.{nombre}'); "
                "usa solo el nombre de tabla.",
            )
        tablas.append(nombre)
        if nombre.lower() not in permitidas_lower:
            return ResultadoValidacion(
                False, f"La tabla '{nombre}' no existe o no está permitida para este agente."
            )

    return ResultadoValidacion(True, tablas=tablas)
