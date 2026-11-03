# Documentación — Asistente IA para Educación

| Documento | Contenido |
|---|---|
| [arquitectura.md](arquitectura.md) | Diseño Agentic AI: orquestación, KB MySQL + Chroma, Reflexion, memoria, evaluación, stack |
| [implementacion.md](implementacion.md) | Código, API JWT, Streamlit, Docker, VPS y pruebas |
| [diagramas-secuencia.md](diagramas-secuencia.md) | Auth, ingest, medios PDF/vídeo, tutoría, examen HITL con Reflexion, consulta SQL, agentes, aislamiento |
| [c4/](c4/) | Modelo C4 (contexto → código) |
| [resultados-pipeline.md](resultados-pipeline.md) | Pipeline JWT E2E (`run_test_pipeline.py --write-doc`): ingest, tutor grounded y Guardrails |
| [revision-implementacion-agentes.md](revision-implementacion-agentes.md) | Pipeline de revisión de agentes (`review_agents_pipeline.py --write-doc`): módulo + fuera_contexto |
| [resultados-sql-agent-pipeline.md](resultados-sql-agent-pipeline.md) | Pipeline SQL Agent + BD sintética + knowledge graph |
| [pruebas-sql-agent-reflexion-aprendizaje.md](pruebas-sql-agent-reflexion-aprendizaje.md) | Evidencia LangSmith: reflexión, KG, refuerzo Chroma y campañas de consulta |
| [costo-computacional-embeddings-contabilidadFinaciera.md](costo-computacional-embeddings-contabilidadFinaciera.md) | Métricas PDF/vídeo: OpenAI vs vLLM USFQ |
| [paper/main.tex](paper/main.tex) | Trabajo de titulación USFQ (IEEE ≤3 págs.): RAG, Reflexion, Guardrails, OpenAI vs LLM locales |

Evaluación y aprendizaje (`eval/`, `scripts/evaluar.py`, `scripts/entrenar_reglas.py`):
[arquitectura.md](arquitectura.md) §5.3–5.5.

## Arranque rápido (camino actual)

```bash
# API JWT
uvicorn src.api.main:app --reload --port 8000

# UI Streamlit
streamlit run app_streamlit/Home.py
```

Demo: `demo@instituto.local` / `demo1234` (tras `python scripts/seed_demo_kb.py`).

Compose (API `:8000` + UI `:8501`): `docker compose up -d --build`.

Producción (VPS): `./scripts/remote.sh deploy` → UI `http://SSH_HOST:8501`, API `http://SSH_HOST:8000`.

### Pipelines documentados (regenerar instantáneas)

```bash
python scripts/run_test_pipeline.py --write-doc          # → docs/resultados-pipeline.md
python scripts/review_agents_pipeline.py --write-doc     # → docs/revision-implementacion-agentes.md
```

Incluyen el escenario Guardrails (petición ajena a la KB → `fuera_contexto`).
Arquitectura y secuencias: [arquitectura.md](arquitectura.md), [implementacion.md](implementacion.md) §4,
[diagramas-secuencia.md](diagramas-secuencia.md) §8–8b, [c4/](c4/).

UX UI (resumen): modelo en sidebar, progreso por fases en Asistente, approve inline,
filtros en Historial, confirmaciones en borrado/HITL. Detalle en [implementacion.md](implementacion.md) §7.

SQL Agent (solo docentes): BD sintética universitaria en
[data/sintetica_academica/](../data/sintetica_academica/) (500 estudiantes + grafo de
conocimiento del esquema). Generar/migrar y cablear `AGENT_DB_URI` /
`SQL_AGENT_KG_PATH` (ver `.env.example`). Pipeline:
`python scripts/run_sql_agent_pipeline.py --write-doc` →
[resultados-sql-agent-pipeline.md](resultados-sql-agent-pipeline.md).
Detalle en [arquitectura.md](arquitectura.md) §6.5 e [implementacion.md](implementacion.md) §5.

Material de origen en `Documentacion/` (requerimiento, base de definición y papers PDF).
El notebook `taller_tenant_kg_v4.ipynb` es la fuente metodológica de los patrones
adaptados aquí (Reflexion, verificador determinista, memoria de casos, juez externo);
las referencias «notebook §…» de los docstrings apuntan a él. No es código en tiempo
de ejecución: la implementación vive en `src/orchestrator/`, `src/rag/` y
`src/evaluation/`.
