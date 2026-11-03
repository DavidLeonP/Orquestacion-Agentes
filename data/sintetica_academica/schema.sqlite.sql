-- DDL SQLite — BD sintética académica (escala notas 0-10)
PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS calificaciones;
DROP TABLE IF EXISTS matriculas;
DROP TABLE IF EXISTS promedios_periodo;
DROP TABLE IF EXISTS ofertas;
DROP TABLE IF EXISTS estudiantes;
DROP TABLE IF EXISTS profesores;
DROP TABLE IF EXISTS materias;
DROP TABLE IF EXISTS paralelos;
DROP TABLE IF EXISTS periodos;
DROP TABLE IF EXISTS carreras;
DROP TABLE IF EXISTS facultades;

CREATE TABLE facultades (
  id INTEGER PRIMARY KEY,
  codigo TEXT NOT NULL UNIQUE,
  nombre TEXT NOT NULL
);

CREATE TABLE carreras (
  id INTEGER PRIMARY KEY,
  facultad_id INTEGER NOT NULL REFERENCES facultades(id),
  codigo TEXT NOT NULL UNIQUE,
  nombre TEXT NOT NULL
);

CREATE TABLE periodos (
  id INTEGER PRIMARY KEY,
  codigo TEXT NOT NULL UNIQUE,
  anio_inicio INTEGER NOT NULL,
  anio_fin INTEGER NOT NULL
);

CREATE TABLE paralelos (
  id INTEGER PRIMARY KEY,
  codigo TEXT NOT NULL UNIQUE
);

CREATE TABLE materias (
  id INTEGER PRIMARY KEY,
  codigo TEXT NOT NULL UNIQUE,
  nombre TEXT NOT NULL,
  creditos INTEGER NOT NULL DEFAULT 3,
  carrera_id INTEGER REFERENCES carreras(id)
);

CREATE TABLE profesores (
  id INTEGER PRIMARY KEY,
  codigo TEXT NOT NULL UNIQUE,
  nombre TEXT NOT NULL,
  email TEXT,
  facultad_id INTEGER NOT NULL REFERENCES facultades(id)
);

CREATE TABLE estudiantes (
  id INTEGER PRIMARY KEY,
  codigo TEXT NOT NULL UNIQUE,
  nombre TEXT NOT NULL,
  email TEXT,
  carrera_id INTEGER NOT NULL REFERENCES carreras(id),
  paralelo_ingreso_id INTEGER NOT NULL REFERENCES paralelos(id),
  anio_ingreso INTEGER NOT NULL
);

CREATE TABLE ofertas (
  id INTEGER PRIMARY KEY,
  periodo_id INTEGER NOT NULL REFERENCES periodos(id),
  materia_id INTEGER NOT NULL REFERENCES materias(id),
  profesor_id INTEGER NOT NULL REFERENCES profesores(id),
  paralelo_id INTEGER NOT NULL REFERENCES paralelos(id),
  UNIQUE (periodo_id, materia_id, paralelo_id)
);

CREATE TABLE matriculas (
  id INTEGER PRIMARY KEY,
  estudiante_id INTEGER NOT NULL REFERENCES estudiantes(id),
  oferta_id INTEGER NOT NULL REFERENCES ofertas(id),
  estado TEXT NOT NULL DEFAULT 'cursando',
  UNIQUE (estudiante_id, oferta_id)
);

CREATE TABLE calificaciones (
  id INTEGER PRIMARY KEY,
  matricula_id INTEGER NOT NULL REFERENCES matriculas(id),
  nota REAL NOT NULL CHECK (nota >= 0 AND nota <= 10),
  convocatoria TEXT NOT NULL DEFAULT 'ordinaria'
);

CREATE TABLE promedios_periodo (
  id INTEGER PRIMARY KEY,
  estudiante_id INTEGER NOT NULL REFERENCES estudiantes(id),
  periodo_id INTEGER NOT NULL REFERENCES periodos(id),
  promedio REAL NOT NULL,
  materia_afinidad_id INTEGER REFERENCES materias(id),
  num_materias INTEGER NOT NULL DEFAULT 0,
  UNIQUE (estudiante_id, periodo_id)
);

CREATE INDEX idx_matriculas_estudiante ON matriculas(estudiante_id);
CREATE INDEX idx_matriculas_oferta ON matriculas(oferta_id);
CREATE INDEX idx_ofertas_periodo ON ofertas(periodo_id);
CREATE INDEX idx_calificaciones_matricula ON calificaciones(matricula_id);
CREATE INDEX idx_promedios_periodo ON promedios_periodo(periodo_id, promedio);
