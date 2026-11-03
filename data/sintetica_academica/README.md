# BD sintética académica (Ecuador)

Datos sintéticos para el **SQL Agent**: 500 estudiantes, 6 años lectivos, 3 paralelos (A/B/C),
materias universitarias y profesores. Universidad ficticia «Universidad Andina Demo (Quito)».

## Flujo

```bash
python scripts/generar_sintetica_academica.py   # → estudiantes_sinteticos.json
python scripts/migrar_sintetica_academica.py    # → data/negocio_academico.db + imprime AGENT_DB_URI
python scripts/run_sql_agent_pipeline.py --write-doc
```

## Parametrización (`.env`)

```env
AGENT_DB_URI=sqlite:////ABS/PATH/Orquestacion-Agentes/data/negocio_academico.db
# En Docker / VPS (volumen data → /app/data):
AGENT_DB_URI=sqlite:////app/data/negocio_academico.db
SQL_AGENT_KG_PATH=data/sintetica_academica/knowledge_graph.json
```

El SQL Agent inyecta el **grafo de conocimiento** (`knowledge_graph.json`) en el system
prompt de `query_gen` para conocer tablas, JOINs y reglas (anti-alucinación).

## Artefactos

| Archivo | Descripción |
|---|---|
| `schema.md` | ER + consultas típicas |
| `schema.sqlite.sql` / `schema.mysql.sql` | DDL |
| `knowledge_graph.json` | Entidades, relaciones, reglas, ejemplos |
| `estudiantes_sinteticos.json` | Fuente canónica (generada) |
| `../negocio_academico.db` | SQLite lista para `AGENT_DB_URI` |

DDL MySQL/MariaDB (`schema.mysql.sql`) permite cargar el mismo modelo en un servidor real.
