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

Material de origen en `Documentacion/` (requerimiento, base de definición y papers PDF).
