# Asistente IA para Educación

Sistema multi-agente (Agentic AI) que asiste a docentes y alumnado de un
instituto, construido con LangChain + LangGraph. Cuatro agentes especializados
(Curriculum, Exam Generator, Rubric y Tutor) coordinados por un orquestador
supervisor, apoyados en la base documental del centro mediante RAG multi-índice
con búsqueda híbrida (BM25 + embeddings).

Documentación:

- [docs/arquitectura.md](docs/arquitectura.md) — directrices de orquestación, conocimiento y aprendizaje
- [docs/implementacion.md](docs/implementacion.md) — API, Docker, despliegue y Postman
- [docs/README.md](docs/README.md) — índice de docs

## Estructura

```
data/                  Base documental del instituto (un índice por carpeta)
  apuntes/  examenes/  rubricas/  curriculo/
src/
  ingestion/           Pipeline de ingesta e indexación
  rag/                 Retriever híbrido (BM25 + Chroma + RRF) y tools RAG
  agents/              Los 4 agentes especializados (ReAct) y schemas
  orchestrator/        Grafo supervisor de LangGraph
  memory/              Memoria de largo plazo (feedback, perfiles, histórico)
docs/arquitectura.md   Documento de arquitectura
main.py                CLI de demostración
```

## Puesta en marcha

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # añade tu OPENAI_API_KEY
```

1. Construir los índices RAG (incluye datos de ejemplo de Tecnología 3º ESO):

```bash
python main.py ingestar
```

2. Ejecutar los escenarios de demostración:

```bash
python main.py demo
```

3. O hacer peticiones directas:

```bash
python main.py docente "Genera un examen de 6 preguntas sobre electricidad para 3º ESO"
python main.py docente "Estructura la unidad de circuitos en sesiones"
python main.py alumno "¿Qué es la ley de Ohm?" alumno-042
```

## Flujo de un examen

1. El router clasifica la petición y la envía al Exam Generator Agent.
2. El agente consulta exámenes históricos, apuntes y rúbricas (bucle ReAct).
3. El Rubric Agent valida el borrador contra los criterios del departamento
   (validación cruzada); si hay incumplimientos, se regenera.
4. El grafo se interrumpe y pide la aprobación del docente (human-in-the-loop).
5. Si se aprueba, el examen pasa al histórico del centro (ciclo de mejora).

Toda respuesta cita las fuentes internas consultadas; los agentes no responden
"en general".
