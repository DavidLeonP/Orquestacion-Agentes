# C4 Nivel 2 — Contenedores

Aplicaciones y almacenes desplegables que forman el sistema.

```mermaid
C4Container
title Contenedores — Asistente IA Educación

Person(usuario, "Usuario", "Docente o alumno autenticado")

System_Boundary(sys, "Asistente IA Educación") {
    Container(api, "API REST", "FastAPI / Uvicorn / Python", "JWT, knowledge, requests, HITL, OpenAPI /docs")
    Container(orq, "Orquestador multi-agente", "LangGraph + LangChain", "Router, 4 agentes ReAct, validación cruzada, interrupt")
    ContainerDb(mysql, "Base de datos", "MySQL", "users, documents, chunks, embeddings, requests, approvals, memoria")
    Container(scripts, "Scripts ops", "Python", "init_db, seed_demo_kb, run_test_pipeline")
}

System_Ext(openai, "OpenAI", "LLM y embeddings")
System_Ext(langsmith, "LangSmith", "Observabilidad opcional")

Rel(usuario, api, "HTTPS JSON", "Bearer JWT")
Rel(api, orq, "In-process", "BackgroundTasks / stream updates")
Rel(api, mysql, "SQL", "CRUD y consultas scoped user_id")
Rel(orq, mysql, "SQL", "RAG chunks/embeddings + memoria LTM")
Rel(orq, openai, "HTTPS", "ChatOpenAI + OpenAIEmbeddings")
Rel(api, openai, "HTTPS", "Embeddings en ingest")
Rel(orq, langsmith, "HTTPS", "Traces si LANGCHAIN_TRACING_V2")
Rel(scripts, mysql, "SQL", "Migración create_all / seed")
Rel(scripts, api, "TestClient / HTTP", "Pipeline de pruebas")
```

## Responsabilidades

| Contenedor | Responsabilidad | Tecnología |
|------------|-----------------|------------|
| API REST | Auth, contratos HTTP, aislamiento JWT, disparo de jobs | FastAPI |
| Orquestador | Clasificación, agentes, HITL, grounding | LangGraph |
| MySQL | Persistencia de identidad, KB y solicitudes | MySQL remoto |
| Scripts | Bootstrap y validación | Python CLI |

## Notas de despliegue

- Hoy API y orquestador corren **en el mismo proceso** (Uvicorn).
- MySQL es **remoto** (`DATABASE_URL`).
- Escalado futuro: workers separados + checkpointer durable compartido + cola (Redis/Celery).
