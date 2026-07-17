# Asistente IA para Educación

Sistema multi-agente (Agentic AI) que asiste a docentes y alumnado, con
**RAG privado por usuario en MySQL**, **API REST JWT** y **UI Streamlit**.
Cuatro agentes (Curriculum, Exam Generator, Rubric, Tutor) coordinados por
LangGraph; LLM/embeddings vía **model registry** (OpenAI u Ollama).

Documentación:

- [docs/arquitectura.md](docs/arquitectura.md) — directrices de orquestación, conocimiento y aprendizaje
- [docs/implementacion.md](docs/implementacion.md) — API JWT, Streamlit, Docker, VPS
- [docs/diagramas-secuencia.md](docs/diagramas-secuencia.md) — flujos de secuencia
- [docs/c4/](docs/c4/) — modelo C4
- [docs/README.md](docs/README.md) — índice de docs

## Estructura

```
data/                  Material de ejemplo / seed (CLI legado)
  apuntes/  examenes/  rubricas/  curriculo/
src/
  api/                 API JWT (auth, knowledge, requests, HITL)
  llm/                 Model registry (OpenAI / Ollama)
  ingestion/           Pipeline MySQL (+ Chroma legado)
  rag/                 Retriever MySQL híbrido + tools RAG
  agents/              Los 4 agentes especializados (ReAct) y schemas
  orchestrator/        Grafo supervisor de LangGraph
  memory/              Memoria de largo plazo
app_streamlit/         UI Streamlit (cliente HTTP de la API)
docs/                  Arquitectura, implementación, C4, secuencias
main.py                CLI de demostración (legado)
scripts/               init_db, seed_demo_kb, pipeline, remote.sh
```

## Puesta en marcha (recomendado)

```bash
python -m venv .venv
# Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env      # DATABASE_URL, JWT_SECRET, OPENAI_API_KEY o LLM_PROFILE
python scripts/init_db.py
python scripts/seed_demo_kb.py
```

```bash
# Terminal 1 — API JWT
uvicorn src.api.main:app --reload --port 8000

# Terminal 2 — UI
streamlit run app_streamlit/Home.py
```

Abre `http://localhost:8501`. Demo: `demo@instituto.local` / `demo1234`.

Swagger: `http://127.0.0.1:8000/docs` · Health: `GET /health`.

### Compose local (API + UI)

```bash
docker compose up -d --build
curl http://localhost:8000/health   # API JWT
open http://localhost:8501          # UI Streamlit
```

### CLI legado (Chroma / `data/`)

```bash
python main.py ingestar
python main.py demo
python main.py docente "Genera un examen de 6 preguntas sobre electricidad para 3º ESO"
python main.py alumno "¿Qué es la ley de Ohm?" alumno-042
```

## UI Streamlit

Cliente HTTP de la API JWT (no embebe LangGraph ni RAG):

| Página | Función |
|--------|---------|
| Home | Login / registro; menú y **modelo activo** tras autenticar |
| Conocimiento | CRUD docs + ingest |
| Asistente | Nueva petición + progreso por pasos (polling) |
| Historial | Solicitudes y eventos legibles |
| Aprobaciones | HITL de exámenes (solo docente) |

Tras el login, el sidebar muestra el modelo activo (`GET /health`) y el menú de navegación.
Al generar un examen, el Asistente muestra pasos (“Clasificando…”, “Generando…”, etc.) y
puede quedar en **pendiente de aprobación** (no es un cuelgue).

Variable: `STREAMLIT_API_BASE_URL` (local `http://127.0.0.1:8000`; en Docker/VPS la red
interna usa el nombre del contenedor API).

## Model registry (OpenAI / Ollama)

Elige proveedor según recursos con `LLM_PROFILE` en `.env`:

| Perfil | Chat | Embeddings |
|--------|------|------------|
| `cloud_openai` | gpt-4o-mini | text-embedding-3-small |
| `local_barato` | qwen2.5:3b (Ollama) | nomic-embed-text |
| `local_calidad` | qwen2.5:7b (Ollama) | nomic-embed-text |

```bash
# Local con Ollama
ollama pull qwen2.5:7b
ollama pull nomic-embed-text
# En .env:
# LLM_PROFILE=local_calidad
# (comenta LLM_MODEL / EMBEDDING_MODEL si quieres que mande el perfil)

# Ver configuración activa
curl http://127.0.0.1:8000/health
```

Overrides: `LLM_PROVIDER`, `LLM_MODEL`, `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, `OLLAMA_BASE_URL`.  
Los agentes y contratos Pydantic no cambian al cambiar de modelo.  
Embeddings de distintos modelos pueden coexistir en MySQL; la búsqueda semántica solo usa el modelo activo (filtro por `chunk_embeddings.model`). Si cambias de embedding, reprocesa la KB para vectores del nuevo modelo (BM25 sigue disponible).

## Flujo de un examen

1. El router clasifica la petición y la envía al Exam Generator Agent.
2. El agente consulta exámenes históricos, apuntes y rúbricas (bucle ReAct).
3. El Rubric Agent valida el borrador contra los criterios del departamento
   (validación cruzada); si hay incumplimientos, se regenera.
4. El grafo se interrumpe y pide la aprobación del docente (human-in-the-loop).
5. Si se aprueba, el examen pasa al histórico del centro (ciclo de mejora).

Toda respuesta cita las fuentes internas consultadas; los agentes no responden
"en general".

## Despliegue y actualización (VPS)

Requisitos en tu Mac: [Docker Desktop](https://www.docker.com/products/docker-desktop/) en ejecución y `sshpass` (`brew install sshpass`).

Configura en `.env` las variables `SSH_HOST`, `SSH_USER`, `SSH_PASSWORD`, `DEPLOY_PATH`,
`API_BASE_URL` y `DOCKER_IMAGE` (ver `.env.example`).

`./scripts/remote.sh deploy` publica **dos contenedores** desde la misma imagen:

| Contenedor | Puerto | Rol |
|---|---|---|
| `asistente-ia-educacion` | `8000` | API JWT (`src.api.main:app`) |
| `asistente-ia-ui` | `8501` | UI Streamlit |

En el VPS, la UI apunta a la API por red Docker (`STREAMLIT_API_BASE_URL=http://asistente-ia-educacion:8000`).

| Comando | Qué hace |
|---|---|
| `./scripts/remote.sh deploy` | Build local → rsync → sube imagen → reinicia **API + UI** |
| `./scripts/remote.sh build` | Solo construye la imagen Docker en local |
| `./scripts/remote.sh push-image` | Transfiere la imagen ya construida al VPS |
| `./scripts/remote.sh rsync` | Sincroniza código y `data/` al servidor (sin imagen) |
| `./scripts/remote.sh restart` | Sube `.env` y recrea API (`:8000`) + UI (`:8501`) |
| `./scripts/remote.sh health` | Comprueba `GET /health` y HTTP de la UI en `:8501` |

Flujo habitual tras cambiar código:

```bash
./scripts/remote.sh deploy
./scripts/remote.sh health
```

Solo cambios de configuración (`.env`) o de scripts de arranque:

```bash
./scripts/remote.sh restart
```

URLs típicas en el VPS (sustituye el host):

- UI: `http://SSH_HOST:8501`
- API: `http://SSH_HOST:8000`
- Swagger: `http://SSH_HOST:8000/docs`
- Health: `GET http://SSH_HOST:8000/health`

Detalle técnico: [docs/implementacion.md](docs/implementacion.md) §§7–8.
