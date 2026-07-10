# C4 Nivel 3 — Componentes (API + orquestación)

Descomposición interna del contenedor API / runtime Python.

```mermaid
C4Component
title Componentes — API y runtime

Container_Boundary(api, "API FastAPI") {
    Component(auth_r, "Router Auth", "src/api/routers/auth.py", "register, login, me")
    Component(know_r, "Router Knowledge", "src/api/routers/knowledge.py", "CRUD docs, ingest, reprocess, chunks")
    Component(req_r, "Router Requests", "src/api/routers/requests.py", "crear, listar, approve, events")
    Component(sec, "Security JWT", "src/api/security.py", "hash, token, decode")
    Component(deps, "Deps", "src/api/deps.py", "get_db, get_current_user")
    Component(runner, "Orchestrator Runner", "src/api/services/orchestrator_runner.py", "Background execute + resume HITL")
}

Container_Boundary(core, "Núcleo multi-agente") {
    Component(graph, "Grafo supervisor", "src/orchestrator/graph.py", "router, nodos, validar, interrupt")
    Component(agents, "Agentes ReAct", "src/agents/*", "curriculum, exam, rubric, tutor")
    Component(tools, "Tools RAG", "src/rag/tools.py", "buscar_* scoped user_id")
    Component(retriever, "Retriever híbrido", "src/rag/mysql_store.py", "BM25 + cosine + RRF")
    Component(ingest, "Pipeline ingest", "src/ingestion/mysql_pipeline.py", "chunk + embed + persist")
    Component(mem, "Memoria LTM", "src/memory/mysql_store.py", "feedback, perfil, histórico")
}

ContainerDb(mysql, "MySQL", "Persistencia")
System_Ext(openai, "OpenAI", "LLM / embeddings")

Rel(auth_r, sec, "usa")
Rel(auth_r, deps, "usa")
Rel(know_r, deps, "usa")
Rel(know_r, ingest, "invoca")
Rel(req_r, deps, "usa")
Rel(req_r, runner, "dispara / resume")
Rel(runner, graph, "stream / Command")
Rel(graph, agents, "ejecutar_agente")
Rel(agents, tools, "tool calls")
Rel(tools, retriever, "buscar")
Rel(retriever, mysql, "SELECT chunks/embeddings")
Rel(ingest, mysql, "INSERT/UPDATE docs chunks")
Rel(ingest, openai, "embeddings")
Rel(agents, openai, "ChatOpenAI")
Rel(graph, mem, "guardar / perfil")
Rel(mem, mysql, "INSERT memoria_*")
Rel(runner, mysql, "UPDATE requests / approvals")
Rel(auth_r, mysql, "users")
Rel(know_r, mysql, "documents")
```

## Mapa componente → tablas MySQL

| Componente | Tablas principales |
|------------|-------------------|
| Auth | `users` |
| Knowledge / Ingest | `documents`, `chunks`, `chunk_embeddings` |
| Requests / Runner | `requests`, `request_events`, `approvals` |
| Memoria | `memory_feedback`, `memory_perfil_alumno`, `memory_historico` |

## ContextVar de aislamiento

Antes de ejecutar el grafo, el runner fija:

- `set_rag_user_id(user_id)` → tools RAG
- `set_memory_user_id(user_id)` → memoria LTM

Así el mismo código de agentes sirve a todos los usuarios sin mezclar KB.
