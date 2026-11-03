-- DDL MySQL/MariaDB — mismo modelo que schema.sqlite.sql (escala notas 0-10)
SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

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

SET FOREIGN_KEY_CHECKS = 1;

CREATE TABLE facultades (
  id INT PRIMARY KEY,
  codigo VARCHAR(16) NOT NULL UNIQUE,
  nombre VARCHAR(120) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE carreras (
  id INT PRIMARY KEY,
  facultad_id INT NOT NULL,
  codigo VARCHAR(16) NOT NULL UNIQUE,
  nombre VARCHAR(160) NOT NULL,
  CONSTRAINT fk_carreras_facultad FOREIGN KEY (facultad_id) REFERENCES facultades(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE periodos (
  id INT PRIMARY KEY,
  codigo VARCHAR(16) NOT NULL UNIQUE,
  anio_inicio INT NOT NULL,
  anio_fin INT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE paralelos (
  id INT PRIMARY KEY,
  codigo VARCHAR(8) NOT NULL UNIQUE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE materias (
  id INT PRIMARY KEY,
  codigo VARCHAR(16) NOT NULL UNIQUE,
  nombre VARCHAR(160) NOT NULL,
  creditos INT NOT NULL DEFAULT 3,
  carrera_id INT NULL,
  CONSTRAINT fk_materias_carrera FOREIGN KEY (carrera_id) REFERENCES carreras(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE profesores (
  id INT PRIMARY KEY,
  codigo VARCHAR(16) NOT NULL UNIQUE,
  nombre VARCHAR(160) NOT NULL,
  email VARCHAR(160) NULL,
  facultad_id INT NOT NULL,
  CONSTRAINT fk_profesores_facultad FOREIGN KEY (facultad_id) REFERENCES facultades(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE estudiantes (
  id INT PRIMARY KEY,
  codigo VARCHAR(24) NOT NULL UNIQUE,
  nombre VARCHAR(160) NOT NULL,
  email VARCHAR(160) NULL,
  carrera_id INT NOT NULL,
  paralelo_ingreso_id INT NOT NULL,
  anio_ingreso INT NOT NULL,
  CONSTRAINT fk_est_carrera FOREIGN KEY (carrera_id) REFERENCES carreras(id),
  CONSTRAINT fk_est_paralelo FOREIGN KEY (paralelo_ingreso_id) REFERENCES paralelos(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE ofertas (
  id INT PRIMARY KEY,
  periodo_id INT NOT NULL,
  materia_id INT NOT NULL,
  profesor_id INT NOT NULL,
  paralelo_id INT NOT NULL,
  UNIQUE KEY uq_oferta (periodo_id, materia_id, paralelo_id),
  CONSTRAINT fk_of_periodo FOREIGN KEY (periodo_id) REFERENCES periodos(id),
  CONSTRAINT fk_of_materia FOREIGN KEY (materia_id) REFERENCES materias(id),
  CONSTRAINT fk_of_profesor FOREIGN KEY (profesor_id) REFERENCES profesores(id),
  CONSTRAINT fk_of_paralelo FOREIGN KEY (paralelo_id) REFERENCES paralelos(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE matriculas (
  id INT PRIMARY KEY,
  estudiante_id INT NOT NULL,
  oferta_id INT NOT NULL,
  estado VARCHAR(32) NOT NULL DEFAULT 'cursando',
  UNIQUE KEY uq_mat (estudiante_id, oferta_id),
  CONSTRAINT fk_mat_est FOREIGN KEY (estudiante_id) REFERENCES estudiantes(id),
  CONSTRAINT fk_mat_oferta FOREIGN KEY (oferta_id) REFERENCES ofertas(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE calificaciones (
  id INT PRIMARY KEY,
  matricula_id INT NOT NULL,
  nota DECIMAL(4,2) NOT NULL,
  convocatoria VARCHAR(32) NOT NULL DEFAULT 'ordinaria',
  CONSTRAINT chk_nota CHECK (nota >= 0 AND nota <= 10),
  CONSTRAINT fk_cal_mat FOREIGN KEY (matricula_id) REFERENCES matriculas(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE promedios_periodo (
  id INT PRIMARY KEY,
  estudiante_id INT NOT NULL,
  periodo_id INT NOT NULL,
  promedio DECIMAL(5,3) NOT NULL,
  materia_afinidad_id INT NULL,
  num_materias INT NOT NULL DEFAULT 0,
  UNIQUE KEY uq_prom (estudiante_id, periodo_id),
  CONSTRAINT fk_prom_est FOREIGN KEY (estudiante_id) REFERENCES estudiantes(id),
  CONSTRAINT fk_prom_per FOREIGN KEY (periodo_id) REFERENCES periodos(id),
  CONSTRAINT fk_prom_mat FOREIGN KEY (materia_afinidad_id) REFERENCES materias(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX idx_matriculas_estudiante ON matriculas(estudiante_id);
CREATE INDEX idx_matriculas_oferta ON matriculas(oferta_id);
CREATE INDEX idx_ofertas_periodo ON ofertas(periodo_id);
CREATE INDEX idx_calificaciones_matricula ON calificaciones(matricula_id);
CREATE INDEX idx_promedios_periodo ON promedios_periodo(periodo_id, promedio);
