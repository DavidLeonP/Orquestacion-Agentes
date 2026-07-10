# C4 Nivel 4 — Vista de código (orquestador y RAG)

Detalle de módulos clave (no es un listado exhaustivo del repo).

## 4.1 Grafo supervisor

```mermaid
flowchart LR
    START([START]) --> router
    router -->|alumno| tutor
    router -->|docente LLM| curriculum
    router -->|docente LLM| exam_generator
    router -->|docente LLM| rubric
    curriculum --> finalizar
    rubric --> finalizar
    tutor --> finalizar
    exam_generator --> validar
    validar -->|APROBADO o max intentos| aprobacion_docente
    validar -->|CAMBIOS| exam_generator
    finalizar --> END([END])
    aprobacion_docente --> END
```

**Archivo:** `src/orchestrator/graph.py`  
**Factory:** `construir_grafo(checkpointer=..., memory_backend=...)`

## 4.2 Pipeline de ingest MySQL

```mermaid
flowchart TD
    Doc[Document pending] --> Split[RecursiveCharacterTextSplitter]
    Split --> Embed[OpenAIEmbeddings.embed_documents]
    Embed --> Del[Borrar chunks previos del document_id]
    Del --> InsC[INSERT chunks]
    InsC --> InsE[INSERT chunk_embeddings]
    InsE --> Idx[status indexed]
    Idx --> Cache[invalidar_cache_retriever]
```

**Archivo:** `src/ingestion/mysql_pipeline.py`

## 4.3 Retriever híbrido

```mermaid
flowchart TD
    Q[consulta] --> Lex[BM25 ranking]
    Q --> Sem[embed_query + cosine]
    Lex --> RRF[RRF fusion k=60]
    Sem --> RRF
    RRF --> TopK[top-k chunks con metadatos fuente]
```

**Archivo:** `src/rag/mysql_store.py`  
**Tools:** `src/rag/tools.py` (`buscar_apuntes`, `buscar_examenes_historicos`, `buscar_rubricas`, `buscar_curriculo`)

## 4.4 Paquetes Python relevantes

| Paquete | Rol |
|---------|-----|
| `src/api/` | Contenedor HTTP |
| `src/db/` | Modelos y sesión SQLAlchemy |
| `src/orchestrator/` | Grafo LangGraph |
| `src/agents/` | Prompts y factories ReAct |
| `src/rag/` | Contexto user_id + retriever + tools |
| `src/ingestion/` | Indexación a MySQL |
| `src/memory/` | LTM MySQL / JSON legacy |
| `src/observability/` | Trazas JSONL + LangSmith |
| `scripts/` | Ops y pipeline de pruebas |
| `tests/` | Pytest smoke API |

## 4.5 Contrato de una solicitud (estados)

```mermaid
stateDiagram-v2
    [*] --> running: POST /requests
    running --> waiting_approval: interrupt examen
    running --> completed: tutor/curriculum/rubric
    running --> failed: excepcion
    waiting_approval --> completed: POST approve
    completed --> [*]
    failed --> [*]
```
