#!/usr/bin/env python3
"""Migra estudiantes_sinteticos.json → SQLite (data/negocio_academico.db).

Uso:
  python scripts/generar_sintetica_academica.py
  python scripts/migrar_sintetica_academica.py
  # Imprime la URI lista para AGENT_DB_URI
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "data" / "sintetica_academica"
JSON_PATH = DIR / "estudiantes_sinteticos.json"
SCHEMA_PATH = DIR / "schema.sqlite.sql"
DB_DEFAULT = ROOT / "data" / "negocio_academico.db"

TABLAS_ORDEN = [
    "facultades",
    "carreras",
    "periodos",
    "paralelos",
    "materias",
    "profesores",
    "estudiantes",
    "ofertas",
    "matriculas",
    "calificaciones",
    "promedios_periodo",
]


def _insert_many(cur: sqlite3.Cursor, tabla: str, filas: list[dict]) -> None:
    if not filas:
        return
    cols = list(filas[0].keys())
    placeholders = ",".join("?" for _ in cols)
    col_sql = ",".join(cols)
    cur.executemany(
        f"INSERT INTO {tabla} ({col_sql}) VALUES ({placeholders})",
        [tuple(f[c] for c in cols) for f in filas],
    )


def migrar(json_path: Path, db_path: Path, schema_path: Path) -> dict[str, int]:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    schema = schema_path.read_text(encoding="utf-8")
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(schema)
        cur = conn.cursor()
        conteos: dict[str, int] = {}
        for tabla in TABLAS_ORDEN:
            filas = data.get(tabla) or []
            _insert_many(cur, tabla, filas)
            conteos[tabla] = len(filas)
        conn.commit()
        return conteos
    finally:
        conn.close()


def uri_sqlite(db_path: Path) -> str:
    return f"sqlite:///{db_path.resolve()}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, default=JSON_PATH)
    parser.add_argument("--db", type=Path, default=DB_DEFAULT)
    parser.add_argument("--schema", type=Path, default=SCHEMA_PATH)
    args = parser.parse_args()

    if not args.json.exists():
        raise SystemExit(
            f"No existe {args.json}. Ejecuta antes: python scripts/generar_sintetica_academica.py"
        )

    conteos = migrar(args.json, args.db, args.schema)
    uri = uri_sqlite(args.db)
    print(f"OK BD: {args.db}")
    for t, n in conteos.items():
        print(f"  {t}: {n}")
    print(f"AGENT_DB_URI={uri}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
