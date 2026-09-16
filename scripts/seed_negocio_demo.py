#!/usr/bin/env python3
"""Crea una BD SQLite de demo para el SQL Agent (matrícula / notas / asistencia).

Uso:
  python scripts/seed_negocio_demo.py
  # escribe data/negocio_demo.db
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "negocio_demo.db"


def main() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.executescript(
            """
            CREATE TABLE alumnos (
              id INTEGER PRIMARY KEY,
              nombre TEXT NOT NULL,
              curso TEXT NOT NULL,
              email TEXT
            );
            CREATE TABLE asignaturas (
              id INTEGER PRIMARY KEY,
              codigo TEXT NOT NULL,
              nombre TEXT NOT NULL
            );
            CREATE TABLE notas (
              id INTEGER PRIMARY KEY,
              alumno_id INTEGER NOT NULL REFERENCES alumnos(id),
              asignatura_id INTEGER NOT NULL REFERENCES asignaturas(id),
              nota REAL NOT NULL,
              convocatoria TEXT NOT NULL
            );
            CREATE TABLE asistencia (
              id INTEGER PRIMARY KEY,
              alumno_id INTEGER NOT NULL REFERENCES alumnos(id),
              fecha TEXT NOT NULL,
              presente INTEGER NOT NULL
            );

            INSERT INTO alumnos (id, nombre, curso, email) VALUES
              (1, 'Ana Pérez', '3º ESO', 'ana@instituto.local'),
              (2, 'Luis Gómez', '3º ESO', 'luis@instituto.local'),
              (3, 'María Ruiz', '4º ESO', 'maria@instituto.local'),
              (4, 'Carlos Díaz', '3º ESO', 'carlos@instituto.local'),
              (5, 'Elena Soto', '4º ESO', 'elena@instituto.local');

            INSERT INTO asignaturas (id, codigo, nombre) VALUES
              (1, 'TEC3', 'Tecnología 3º ESO'),
              (2, 'MAT3', 'Matemáticas 3º ESO'),
              (3, 'TEC4', 'Tecnología 4º ESO');

            INSERT INTO notas (alumno_id, asignatura_id, nota, convocatoria) VALUES
              (1, 1, 8.5, 'ordinaria'),
              (1, 2, 7.0, 'ordinaria'),
              (2, 1, 6.0, 'ordinaria'),
              (2, 2, 9.0, 'ordinaria'),
              (3, 3, 8.0, 'ordinaria'),
              (4, 1, 9.5, 'ordinaria'),
              (4, 2, 8.5, 'ordinaria'),
              (5, 3, 5.5, 'ordinaria');

            INSERT INTO asistencia (alumno_id, fecha, presente) VALUES
              (1, '2025-10-01', 1),
              (1, '2025-10-02', 1),
              (1, '2025-10-03', 0),
              (2, '2025-10-01', 1),
              (2, '2025-10-02', 0),
              (2, '2025-10-03', 1),
              (4, '2025-10-01', 1),
              (4, '2025-10-02', 1),
              (4, '2025-10-03', 1);
            """
        )
        conn.commit()
        print(f"Creada {DB_PATH}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
