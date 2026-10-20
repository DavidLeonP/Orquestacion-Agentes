# Documentación — Asistente IA para Educación

| Documento | Contenido |
|---|---|
| [arquitectura.md](arquitectura.md) | Diseño Agentic AI: orquestación, KB MySQL + Chroma, Reflexion, memoria, evaluación, stack |
| [implementacion.md](implementacion.md) | Código, API JWT, Streamlit, Docker, VPS y pruebas |
| [diagramas-secuencia.md](diagramas-secuencia.md) | Auth, ingest, medios PDF/vídeo, tutoría, examen HITL con Reflexion, consulta SQL, agentes, aislamiento |
| [c4/](c4/) | Modelo C4 (contexto → código) |
| [resultados-pipeline.md](resultados-pipeline.md) | Resultados de ejecución del pipeline vía API (instantánea) |
| [costo-computacional-embeddings-contabilidadFinaciera.md](costo-computacional-embeddings-contabilidadFinaciera.md) | Métricas PDF/vídeo: OpenAI vs vLLM USFQ |
| [revision-implementacion-agentes.md](revision-implementacion-agentes.md) | Salida del pipeline de revisión de agentes (instantánea generada) |

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

UX UI (resumen): modelo en sidebar, progreso por fases en Asistente, approve inline,
filtros en Historial, confirmaciones en borrado/HITL. Detalle en [implementacion.md](implementacion.md) §7.

SQL Agent (solo docentes): configura `AGENT_DB_URI` en `.env` y usa la página
**Consultas SQL** para preguntar en lenguaje natural sobre la BD de negocio.
Detalle en [arquitectura.md](arquitectura.md) §6.5 e [implementacion.md](implementacion.md) §5.

Material de origen en `Documentacion/` (requerimiento, base de definición y papers PDF).
El notebook `taller_tenant_kg_v4.ipynb` es la fuente metodológica de los patrones
adaptados aquí (Reflexion, verificador determinista, memoria de casos, juez externo);
las referencias «notebook §…» de los docstrings apuntan a él. No es código en tiempo
de ejecución: la implementación vive en `src/orchestrator/`, `src/rag/` y
`src/evaluation/`.
