# C4 Nivel 3 — Componentes (API + orquestación)

Descomposición interna del contenedor API / runtime Python.

```mermaid
C4Component
title Componentes — API y runtime

Container_Boundary(api, "API FastAPI") {
    Component(auth_r, "Router Auth", "src/api/routers/auth.py", "register, login, me")
    Component(know_r, "Router Knowledge", "src/api/routers/knowledge.py", "CRUD docs, ingest, reprocess, chunks")
    Component(req_r, "Router Requests", "src/api/routers/requests.py", "crear, listar, approve, events")
    Component(sql_r, "Router SQL Agent", "src/api/routers/sql_agent.py", "crear, listar, detalle, events (solo docente)")
    Component(sec, "Security JWT", "src/api/security.py", "hash, token, decode")
    Component(deps, "Deps", "src/api/deps.py", "get_db, get_current_user")
    Component(runner, "Orchestrator Runner", "src/api/services/orchestrator_runner.py", "Background execute + resume HITL")
    Component(sqlrunner, "SQL Agent Runner", "src/api/services/sql_agent_runner.py", "Background execute + eventos por nodo")
}

Container_Boundary(core, "Núcleo multi-agente") {
    Component(graph, "Grafo supervisor", "src/orchestrator/graph.py", "router, nodos, validar, reflexionar, interrupt")
    Component(routing, "Router por reglas", "src/orchestrator/routing.py", "verbo + objeto; LLM si es ambiguo")
    Component(reflexion, "Reflexion y verificador", "src/orchestrator/reflexion.py", "verificar_examen, modo_reintento, mejor_intento")
    Component(criterios, "Criterios de rúbrica", "src/orchestrator/criterios.py", "rúbrica → CriteriosRubrica (cache por hash)")
    Component(agents, "Agentes ReAct", "src/agents/*", "create_agent + middleware; curriculum, exam, rubric, tutor")
    Component(schemas, "Contratos Pydantic", "src/agents/schemas.py", "examen, veredicto, aprobación, reflexión, criterios")
    Component(registry, "Model registry", "src/llm/registry.py", "get_chat_model / get_embeddings")
    Component(tools, "Tools RAG", "src/rag/tools.py", "buscar_* scoped user_id; anotan evidencia")
    Component(retriever, "Retriever híbrido", "src/rag/mysql_store.py", "BM25 + Chroma HNSW + RRF")
    Component(vectores, "Índice Chroma", "src/rag/kb_vectores.py + chroma_client.py", "upsert, borrar, sincronizar, buscar")
    Component(ingest, "Pipeline ingest", "src/ingestion/mysql_pipeline.py", "chunk + embed + persist")
    Component(media, "Extractores medios", "src/ingestion/extractors/*", "PDF pypdf + vídeo Whisper")
    Component(modload, "Module media", "src/ingestion/module_media.py", "inventario, dry-run, commit MySQL")
    Component(mem, "Memoria LTM", "src/memory/mysql_store.py", "feedback, perfil, histórico")
    Component(casos, "Memoria de casos y reglas", "src/memory/casos.py + reglas.py", "exámenes aprobados (Chroma) + manual JSON")
    Component(evaluacion, "Evaluación offline", "src/evaluation/*", "juez externo, métricas, entrenamiento")
}

Container_Boundary(sqlcore, "SQL Agent") {
    Component(sqlgraph, "Grafo SQL Agent", "src/sql_agent/graph.py", "query_gen, correct_query, execute_query, exigir_consulta")
    Component(sqltools, "Tools SQL", "src/sql_agent/tools.py", "list_tables, get_schema, db_query_tool, ProponerConsultaSQL")
    Component(validator, "Validador AST", "src/sql_agent/sql_validator.py", "sqlglot: solo SELECT, whitelist de tablas")
    Component(executor, "Ejecutor trust-no-one", "src/sql_agent/executor.py", "revalida antes de ejecutar")
    Component(bizdbconn, "Conexión BD negocio", "src/sql_agent/database.py", "cache por tenant, SESSION READ ONLY")
}

ContainerDb(mysql, "MySQL", "Persistencia de metadatos")
ContainerDb(bizdb, "BD de negocio", "AGENT_DB_URI")
System_Ext(llmprov, "OpenAI / vLLM / Ollama", "LLM / embeddings / ASR")

Rel(auth_r, sec, "usa")
Rel(auth_r, deps, "usa")
Rel(know_r, deps, "usa")
Rel(know_r, ingest, "invoca")
Rel(req_r, deps, "usa")
Rel(req_r, runner, "dispara / resume")
Rel(sql_r, deps, "usa")
Rel(sql_r, sqlrunner, "dispara")
Rel(runner, graph, "stream / Command")
Rel(sqlrunner, sqlgraph, "stream")
Rel(graph, agents, "ejecutar_agente")
Rel(graph, schemas, "estado tipado")
Rel(agents, tools, "tool calls")
Rel(agents, registry, "chat model")
Rel(tools, retriever, "buscar")
Rel(retriever, mysql, "SELECT chunks (BM25)")
Rel(retriever, vectores, "HNSW / sincronizar")
Rel(ingest, vectores, "upsert / borrar")
Rel(graph, routing, "enrutar_por_reglas")
Rel(graph, reflexion, "decisiones puras")
Rel(graph, criterios, "cargar_criterios")
Rel(graph, casos, "recordar / archivar / cargar manual")
Rel(evaluacion, graph, "corre hasta HITL")
Rel(retriever, registry, "modelo embedding activo")
Rel(ingest, mysql, "INSERT/UPDATE docs chunks")
Rel(ingest, registry, "embeddings")
Rel(modload, media, "extrae PDF/vídeo")
Rel(media, llmprov, "Whisper / ASR compatible")
Rel(modload, ingest, "indexar tras texto")
Rel(registry, llmprov, "API compatible OpenAI")
Rel(graph, mem, "guardar / perfil")
Rel(mem, mysql, "INSERT memoria_*")
Rel(runner, mysql, "UPDATE requests / approvals")
Rel(auth_r, mysql, "users")
Rel(know_r, mysql, "documents")
Rel(sqlgraph, sqltools, "tool calls")
Rel(sqlgraph, registry, "chat model")
Rel(sqltools, executor, "db_query_tool")
Rel(executor, validator, "revalida AST")
Rel(executor, bizdbconn, "ejecuta si válida")
Rel(bizdbconn, bizdb, "SELECT / SESSION READ ONLY")
Rel(sqlrunner, mysql, "UPDATE sql_queries / sql_query_events")
```

## Mapa componente → tablas MySQL

| Componente | Tablas principales |
|------------|-------------------|
| Auth | `users` |
| Knowledge / Ingest / Module media | `documents`, `chunks`, `chunk_embeddings` |
| Requests / Runner | `requests`, `request_events`, `approvals` |
| SQL Agent / Runner | `sql_queries`, `sql_query_events` (metadatos); tablas de negocio en `AGENT_DB_URI` |
| Memoria | `memory_feedback`, `memory_perfil_alumno`, `memory_historico` (+ Chroma `casos_<modelo>` y `storage/reglas_aprendidas.json`) |
| Criterios de rúbrica | lee `chunks` del índice `rubricas` |

## ContextVar de aislamiento

Antes de ejecutar el grafo, el runner fija:

- `set_rag_user_id(user_id)` → tools RAG y memoria de casos
- `set_memory_user_id(user_id)` → memoria LTM

El CLI (`main.py`), la API legado y la evaluación usan `contexto_usuario(user_id)`
(`src/contexto_usuario.py`), que fija y restaura los dos. Una tercera ContextVar
(`iniciar_evidencia` en `src/rag/context.py`) recoge las fuentes que devuelven las tools
durante el agente en curso, para que el verificador rechace citas inventadas.

Así el mismo código de agentes sirve a todos los usuarios sin mezclar KB.

El SQL Agent usa un mecanismo distinto y más estricto: en vez de un `ContextVar`
ambiental, `tenant` (= `user_id` del docente) viaja como **argumento explícito y
obligatorio** por todas las capas (`construir_grafo` → `build_sql_tools` →
`ejecutar_sql_validado`), para que un bug de wiring no pueda ejecutar SQL sin que
quede claro a qué usuario pertenece la conexión cacheada a la BD de negocio.
