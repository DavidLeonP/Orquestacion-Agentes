# C4 Nivel 1 — Contexto del sistema

Vista de personas y sistemas externos que interactúan con el Asistente IA para Educación.

```mermaid
C4Context
title Contexto del sistema — Asistente IA Educación

Person(docente, "Docente", "Planifica, genera exámenes y aprueba material")
Person(alumno, "Alumno", "Consulta dudas con el Tutor Agent")
Person(dev, "Desarrollador / Ops", "Despliega API, migra MySQL, observa trazas")

System(asistente, "Asistente IA Educación", "API multi-agente con RAG privado por usuario, orquestación LangGraph e HITL")

System_Ext(ui, "UI Streamlit", "Cliente HTTP JWT: login, KB, requests, aprobaciones")
System_Ext(llmprov, "OpenAI u Ollama", "Chat y embeddings según LLM_PROFILE")
System_Ext(mysql, "MySQL", "Usuarios, documentos, chunks, embeddings, requests, memoria")
System_Ext(langsmith, "LangSmith", "Trazas opcionales de LangChain/LangGraph")

Rel(docente, ui, "Usa la app", "Páginas por rol")
Rel(alumno, ui, "Usa la app", "Tutoría y KB propia")
Rel(ui, asistente, "HTTPS / JWT", "REST OpenAPI")
Rel(docente, asistente, "HTTPS / JWT opcional", "Postman / scripts")
Rel(alumno, asistente, "HTTPS / JWT opcional", "Postman / scripts")
Rel(dev, asistente, "Deploy / scripts", "init_db, seed, pipeline pruebas")
Rel(asistente, llmprov, "HTTPS o local", "Chat completions y embeddings")
Rel(asistente, mysql, "TCP 3306", "SQLAlchemy / PyMySQL")
Rel(asistente, langsmith, "HTTPS", "Tracing opcional")
```

## Alcance

- **Dentro del sistema:** API FastAPI, orquestador LangGraph, agentes ReAct, retriever híbrido MySQL, ingest, model registry.
- **Fuera del sistema:** OpenAI/Ollama, MySQL gestionado, LangSmith, UI Streamlit (proceso aparte), Postman/scripts.

## Decisiones de contexto

1. El conocimiento es **por usuario**, no un corpus institucional compartido.
2. El backend es el producto estable; Streamlit es un **cliente** (no embebe LangGraph/RAG).
3. MySQL es la fuente de verdad de KB y gestión (no Chroma en el flujo API).
4. El proveedor LLM es intercambiable vía `LLM_PROFILE` sin cambiar contratos de agentes.
