# Asistente IA para Educación

Sistema multi-agente (LangChain + LangGraph) con **API REST**, **JWT** y
conocimiento RAG **privado por usuario** persistido en **MySQL**.

Cuatro agentes (Curriculum, Exam Generator, Rubric, Tutor) coordinados por un
orquestador supervisor. Detalle de diseño en
[docs/arquitectura.md](docs/arquitectura.md).
Diagramas de secuencia: [docs/diagramas-secuencia.md](docs/diagramas-secuencia.md).
Modelo C4: [docs/c4/](docs/c4/).

## Arranque rápido (API)

```powershell
cd "C:\xxxx\Orquestacion-Agentes"
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
# Configura .env: OPENAI_API_KEY, DATABASE_URL, JWT_SECRET

$env:PYTHONPATH = (Get-Location).Path
python scripts\init_db.py
uvicorn src.api.main:app --reload --host 127.0.0.1 --port 8000
```

- OpenAPI: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- Health: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)

### Usuario demo

| Campo | Valor |
|-------|--------|
| Email | `demo@instituto.local` |
| Password | `demo1234` |
| Rol | `docente` |
| KB | 6 documentos Tecnología 3º ESO (si corriste el seed) |

```powershell
$login = Invoke-RestMethod -Method POST -Uri http://127.0.0.1:8000/auth/login `
  -ContentType "application/json" `
  -Body '{"email":"demo@instituto.local","password":"demo1234"}'
$h = @{ Authorization = "Bearer $($login.access_token)" }

Invoke-RestMethod -Uri http://127.0.0.1:8000/knowledge/documents -Headers $h

$req = Invoke-RestMethod -Method POST -Uri http://127.0.0.1:8000/requests `
  -Headers $h -ContentType "application/json" `
  -Body '{"peticion":"Estructura la unidad de circuitos en 3 sesiones"}'

Invoke-RestMethod -Uri "http://127.0.0.1:8000/requests/$($req.id)" -Headers $h

# Si status = waiting_approval (examen):
# Invoke-RestMethod -Method POST -Uri "http://127.0.0.1:8000/requests/$($req.id)/approve" `
#   -Headers $h -ContentType "application/json" -Body '{"decision":"si"}'
```

## Endpoints

**Auth**

- `POST /auth/register` — `{ email, password, rol: docente|alumno }`
- `POST /auth/login` — JWT
- `GET /auth/me`

**Conocimiento (MySQL, por usuario)**

- `POST /knowledge/{indice}/documents` — `apuntes` \| `examenes` \| `rubricas` \| `curriculo`
- `GET /knowledge/documents` · `GET /knowledge/documents/{id}`
- `PATCH /knowledge/documents/{id}` · `DELETE /knowledge/documents/{id}`
- `POST /knowledge/ingest` · `POST /knowledge/documents/{id}/reprocess`
- `GET /knowledge/chunks`

**Solicitudes**

- `POST /requests` — orquestador en background
- `GET /requests` · `GET /requests/{id}`
- `POST /requests/{id}/approve` — HITL docente
- `GET /requests/{id}/events`

## Persistencia

| Dato | Dónde |
|------|--------|
| Usuarios, documentos, chunks, embeddings | MySQL (`DATABASE_URL`) |
| Solicitudes, approvals, memoria LTM | MySQL |
| Búsqueda semántica | `chunk_embeddings` + coseno en app |
| Búsqueda léxica | BM25 sobre `chunks` del usuario |

En el flujo API **no** se usa Chroma ni `storage/chunks/*.json`. Cada usuario solo
consulta su propia base de conocimiento.

## Pipeline de pruebas

```powershell
$env:PYTHONPATH = (Get-Location).Path

# Smoke (auth + CRUD, sin OpenAI)
python scripts\run_test_pipeline.py --smoke

# Full (ingest + LLM + orquestador)
python scripts\run_test_pipeline.py

# Pytest
pytest tests\test_pipeline_api.py -v
```

## Seed demo

```powershell
$env:PYTHONPATH = (Get-Location).Path
# Requiere usuario demo registrado
python scripts\seed_demo_kb.py
```

## Estructura

```
src/
  api/           FastAPI (auth, knowledge, requests)
  db/            Modelos SQLAlchemy + sesión MySQL
  ingestion/     Pipeline chunk + embed → MySQL
  rag/           Retriever híbrido MySQL + tools
  agents/        Curriculum, Exam, Rubric, Tutor (ReAct)
  orchestrator/  Grafo LangGraph + HITL
  memory/        Memoria MySQL (API) / JSON (CLI legacy)
  observability/ Trazas JSONL + LangSmith
scripts/
  init_db.py
  seed_demo_kb.py
  run_test_pipeline.py
tests/
  test_pipeline_api.py
docs/
  arquitectura.md
  diagramas-secuencia.md
  c4/                  Contexto, contenedores, componentes, código
main.py          CLI legacy (opcional)
```

## Variables `.env`

```env
OPENAI_API_KEY=...
LLM_MODEL=gpt-4o-mini
EMBEDDING_MODEL=text-embedding-3-small
DATABASE_URL=mysql+pymysql://USER:PASS@HOST:3306/DB
JWT_SECRET=...
JWT_EXPIRE_MINUTES=1440
CORS_ORIGINS=*
# LangSmith opcional
# LANGCHAIN_TRACING_V2=true
# LANGCHAIN_API_KEY=...
# LANGCHAIN_PROJECT=orquestacion-agentes-educacion
```

## Flujo de un examen (API)

1. `POST /requests` con la petición de generar examen.
2. Exam Generator consulta la KB del usuario (ReAct).
3. Rubric Agent valida (`VEREDICTO: APROBADO` / `CAMBIOS REQUERIDOS`).
4. Status `waiting_approval` con borrador + veredicto.
5. `POST /requests/{id}/approve` → respuesta final y memoria MySQL.

## CLI legacy

`python main.py docente|alumno|demo|ingestar` sigue disponible para demos locales
con el stack anterior (Chroma/JSON). El camino estable para frontend es la **API REST**.
