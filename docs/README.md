# Documentación — Asistente IA para Educación

| Documento | Contenido |
|---|---|
| [arquitectura.md](arquitectura.md) | Diseño Agentic AI: orquestación, KB MySQL por usuario, model registry, stack |
| [implementacion.md](implementacion.md) | Código, API JWT, Streamlit, Docker, VPS y pruebas |
| [diagramas-secuencia.md](diagramas-secuencia.md) | Auth, ingest, tutoría, examen HITL, aislamiento |
| [c4/](c4/) | Modelo C4 (contexto → código) |
| [resultados-pipeline.md](resultados-pipeline.md) | Resultados de ejecución del pipeline vía API |

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
filtros en Historial, confirmaciones en borrado/HITL. Detalle en [implementacion.md](implementacion.md) §6.

Material de origen en `Documentacion/` (requerimiento, base de definición y papers PDF).
