# Resultados — pipeline SQL Agent (BD sintética académica)

**Generado (UTC):** 2026-11-03T15:35:49.126527+00:00
**Resultado global:** PASS
**AGENT_DB_URI:** `sqlite:////Users/peluchito/Desktop/Orquestacion-Agentes/data/negocio_academico.db`
**Knowledge graph:** `data/sintetica_academica/knowledge_graph.json`

## Checks

| Check | OK | Detalle |
|---|---|---|
| `generar_json` | ✅ | ya existe estudiantes_sinteticos.json |
| `migrar_sqlite` | ✅ | estudiantes=500 calificaciones=8711 |
| `knowledge_graph` | ✅ | entidades=11 relaciones=15 |
| `kg_contexto_prompt` | ✅ | len=4280 |
| `kg_regla_anio_pasado` | ✅ | regla temporal en KG |
| `seed_clarificacion_chroma` | ✅ | id=88da6dbfb5584d2fafb8d8b607fc1dd4 hits=2 |
| `sql_top10_2023` | ✅ | primero=('EST-0476', 'Benjamín Silva Guerrero', 8.94) |
| `sql_promedio_paralelo_calculo` | ✅ | [('A', 7.141), ('B', 7.0), ('C', 7.153)] |
| `agent_top10` | ✅ | t=11.32s sql_ok=True preview='Los 10 estudiantes con mejor promedio en el periodo 2023-2024 son:\n\n1. **Código:** EST-0476, **Nombre:** Benjamín Silva Guerrero, **Promedio:** 8.94\n2. **Código:** EST |
| `agent_paralelo` | ✅ | t=9.19s sql_ok=True preview='El promedio de notas del paralelo B en la materia Cálculo I (MAT101) es de aproximadamente 7.00.' |
| `agent_anio_pasado` | ✅ | t=14.61s sql_ok=True preview='Los estudiantes que se matricularon el año pasado (2024-2025) son:\n\n1. Código: EST-0001, Nombre: Carlos Ruiz Silva, Carrera: SIS, Periodo: 2024-2025\n2. Código: EST-000 |
| `agent_fuera_esquema` | ✅ | t=8.09s sql_ok=True preview='No pude generar una consulta SQL válida tras 10 intentos. Reformula la pregunta o revisa que las tablas necesarias existan.' |

## Cómo reproducir

```bash
python scripts/generar_sintetica_academica.py
python scripts/migrar_sintetica_academica.py
python scripts/seed_clarificacion_sql_anio_pasado.py --tenant pipeline-sintetica
python scripts/run_sql_agent_pipeline.py --write-doc
```

Parametrización: `AGENT_DB_URI`, `SQL_AGENT_KG_PATH`, `UMBRAL_MEMORIA_SQL`, `MAX_SQL_AGENT_VALIDACIONES`.
Reflexión SQL: validación → `reflexionar` / `aclaracion_humana` (HITL) → Chroma `clarificaciones_sql_*`.
Aclaración humana en API: `POST /sql-queries/{id}/clarify`.
