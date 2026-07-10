# C4 Nivel 1 — Contexto del sistema

Vista de personas y sistemas externos que interactúan con el Asistente IA para Educación.

```mermaid
C4Context
title Contexto del sistema — Asistente IA Educación

Person(docente, "Docente", "Planifica, genera exámenes y aprueba material")
Person(alumno, "Alumno", "Consulta dudas con el Tutor Agent")
Person(dev, "Desarrollador / Ops", "Despliega API, migra MySQL, observa trazas")

System(asistente, "Asistente IA Educación", "API multi-agente con RAG privado por usuario, orquestación LangGraph e HITL")

System_Ext(openai, "OpenAI API", "LLM gpt-4o-mini y embeddings text-embedding-3-small")
System_Ext(mysql, "MySQL", "Usuarios, documentos, chunks, embeddings, requests, memoria")
System_Ext(langsmith, "LangSmith", "Trazas opcionales de LangChain/LangGraph")
System_Ext(frontend, "Frontend futuro", "Cliente web/móvil que consumirá la API REST")

Rel(docente, asistente, "HTTPS / JWT", "Auth, knowledge, requests, approve")
Rel(alumno, asistente, "HTTPS / JWT", "Auth, knowledge propia, requests tutoría")
Rel(frontend, asistente, "REST OpenAPI", "Cuando exista UI")
Rel(dev, asistente, "Deploy / scripts", "init_db, seed, pipeline pruebas")
Rel(asistente, openai, "HTTPS", "Chat completions y embeddings")
Rel(asistente, mysql, "TCP 3306", "SQLAlchemy / PyMySQL")
Rel(asistente, langsmith, "HTTPS", "Tracing opcional")
```

## Alcance

- **Dentro del sistema:** API FastAPI, orquestador LangGraph, agentes ReAct, retriever híbrido, lógica de ingest.
- **Fuera del sistema:** OpenAI, MySQL gestionado, LangSmith, clientes (hoy curl/Postman/scripts; mañana frontend).

## Decisiones de contexto

1. El conocimiento es **por usuario**, no un corpus institucional compartido.
2. El backend es el producto estable; el frontend se construye después sobre OpenAPI.
3. MySQL es la fuente de verdad de KB y gestión (no Chroma en el flujo API).
