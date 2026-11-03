# Resultados de ejecución del pipeline (API JWT)

> Instantánea generada por `scripts/run_test_pipeline.py --write-doc`. Incluye ingest RAG, orquestador grounded y Guardrails de cobertura KB. Diseño: [arquitectura.md](arquitectura.md).

**Fecha (UTC):** 2026-11-02T18:48:46.878872+00:00
**Modo:** `full (ingest + LLM + Guardrails)` (TestClient → `src.api.main:app`)
**Usuario temporal:** `test_accdb32d95@pipeline.test`
**Estado:** PASS (16/16 pasos)
**Script:** [`scripts/run_test_pipeline.py`](../scripts/run_test_pipeline.py)

## Resumen ejecutivo

| Paso | OK | Detalle |
|---|---|---|
| `GET /health` | ✅ | {"status":"ok","llm":{"profile":"cloud_openai","llm_provider":"openai","llm_model":"gpt-4o-mini","embedding_provider":"openai","embedding_model":"text-embedding |
| `POST /auth/register` | ✅ | id=80 |
| `POST /auth/login` | ✅ |  |
| `GET /auth/me` | ✅ | docente |
| `POST /knowledge/apuntes/documents` | ✅ | doc=45 |
| `GET /knowledge/documents` | ✅ | n=1 |
| `PATCH /knowledge/documents/{id}` | ✅ | pending |
| `POST /knowledge/ingest` | ✅ | {'procesados': 1, 'errores': 0, 'detalle': [{'document_id': 45, 'filename': 'pipeline_ohm.txt', 'chunks': 1}]} |
| `GET /knowledge/chunks (RAG MySQL)` | ✅ | n=1 |
| `POST /requests` | ✅ | id=35 status=running |
| `Orquestador responde (GET /requests/{id})` | ✅ | status=completed len=730 |
| `Respuesta parece grounded en KB` | ✅ | La ley de Ohm establece la relación entre la tensión (V), la corriente (I) y la resistencia (R) en un circuito eléctrico |
| `GET /requests/{id}/events` | ✅ | n=4 |
| `POST /requests (fuera de contexto)` | ✅ | id=36 |
| `Guardrails bloquea fuera de contexto` | ✅ | status=completed agente=fuera_contexto preview='No puedo atender esta petición con el material de la sesión actual: no hay evidencia suficiente en la base docum |
| `Cleanup usuario de prueba` | ✅ |  |

**Veredicto:** con Guardrails activos, el pipeline JWT indexa material en MySQL/Chroma, el orquestador responde anclado a la KB de la sesión y rechaza peticiones fuera de contexto (p. ej. Renacimiento / teoría del color cuando la KB es electricidad) sin inventar un examen.

## Guardrails observados

- Umbrales (`src/config.py`): `UMBRAL_COBERTURA_KB=0.38`, `UMBRAL_COBERTURA_LEX=0.20`,
  `UMBRAL_COBERTURA_SEM_FUERTE=0.55` (el top-1 HNSW solo no abre la puerta).
- Router → nodo `fuera_contexto` si `evaluar_cobertura` falla.
- Middleware `GroundingGuardrailMiddleware` + PII email en cada agente ReAct
  ([LangChain Guardrails](https://docs.langchain.com/oss/python/langchain/guardrails)).
- Constraints del examen ancladas al material recuperado (sin forzar `6 preguntas` / temas ajenos).
- En esta corrida: petición Renacimiento → `agente=fuera_contexto`, tutor Ohm → grounded.

## Cómo reproducir

```bash
python scripts/run_test_pipeline.py --write-doc
# solo auth/CRUD:
python scripts/run_test_pipeline.py --smoke
```

Nota: el script histórico `scripts/run_pipeline_api.py` apunta a la API legado `/api/v1/*`. El camino actual es JWT (`/auth`, `/knowledge`, `/requests`).
