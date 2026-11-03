# Esquema ER — BD sintética académica (Ecuador)

Universidad ficticia estilo Quito/USFQ. Escala de notas **0–10**.
Fuente canónica: `estudiantes_sinteticos.json` → migración a `data/negocio_academico.db`.

## Diagrama

Vista renderizada: [`docs/diagramas/er-bd-sintetica-academica.jpg`](../../docs/diagramas/er-bd-sintetica-academica.jpg)

```mermaid
erDiagram
  facultades {
    int id PK
    text codigo UK
    text nombre
  }
  carreras {
    int id PK
    int facultad_id FK
    text codigo UK
    text nombre
  }
  periodos {
    int id PK
    text codigo UK
    int anio_inicio
    int anio_fin
  }
  paralelos {
    int id PK
    text codigo UK
  }
  materias {
    int id PK
    text codigo UK
    text nombre
    int creditos
    int carrera_id FK
  }
  profesores {
    int id PK
    text codigo UK
    text nombre
    text email
    int facultad_id FK
  }
  estudiantes {
    int id PK
    text codigo UK
    text nombre
    text email
    int carrera_id FK
    int paralelo_ingreso_id FK
    int anio_ingreso
  }
  ofertas {
    int id PK
    int periodo_id FK
    int materia_id FK
    int profesor_id FK
    int paralelo_id FK
  }
  matriculas {
    int id PK
    int estudiante_id FK
    int oferta_id FK
    text estado
  }
  calificaciones {
    int id PK
    int matricula_id FK
    real nota
    text convocatoria
  }
  promedios_periodo {
    int id PK
    int estudiante_id FK
    int periodo_id FK
    real promedio
    int materia_afinidad_id FK
    int num_materias
  }

  facultades ||--o{ carreras : tiene
  facultades ||--o{ profesores : emplea
  carreras ||--o{ estudiantes : matricula
  carreras ||--o{ materias : ofrece
  paralelos ||--o{ estudiantes : ingreso
  periodos ||--o{ ofertas : abre
  materias ||--o{ ofertas : ofertada
  profesores ||--o{ ofertas : imparte
  paralelos ||--o{ ofertas : seccion
  estudiantes ||--o{ matriculas : se_inscribe
  ofertas ||--o{ matriculas : en
  matriculas ||--o{ calificaciones : evaluada
  estudiantes ||--o{ promedios_periodo : resume
  periodos ||--o{ promedios_periodo : resume
  materias ||--o{ promedios_periodo : afinidad
```

## Tablas

| Tabla | Rol |
|---|---|
| `facultades` | Catálogo de facultades |
| `carreras` | Carreras por facultad |
| `periodos` | 6 años lectivos (p. ej. 2019-2020 … 2024-2025) |
| `paralelos` | Secciones A, B, C |
| `materias` | Catálogo universitario (créditos) |
| `profesores` | Docentes vinculados a facultad |
| `estudiantes` | 500 alumnos sintéticos |
| `ofertas` | Materia + periodo + paralelo + profesor |
| `matriculas` | Estudiante inscrito en una oferta |
| `calificaciones` | Nota 0–10 por matrícula |
| `promedios_periodo` | Promedio y afinidad (materia top) por estudiante/periodo |

## Consultas típicas del SQL Agent

- Top 10 estudiantes por `promedio` en un `periodos.codigo`
- Promedio de notas por `paralelos.codigo` y materia
- Afinidad: `promedios_periodo.materia_afinidad_id` / mejor nota media
- Carga docente: conteo de `ofertas` por profesor
- Evolución de un estudiante a lo largo de los 6 periodos
