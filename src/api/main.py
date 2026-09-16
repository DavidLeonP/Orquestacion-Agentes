"""Aplicación FastAPI — Asistente IA Educación."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routers import auth, knowledge, requests, sql_agent
from src.config import CORS_ORIGINS

app = FastAPI(
    title="Orquestación Agentes Educación",
    description=(
        "API REST multi-agente con conocimiento RAG privado por usuario "
        "(MySQL). Auth JWT, ingest a demanda, solicitudes y HITL de exámenes."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS if CORS_ORIGINS != ["*"] else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(knowledge.router)
app.include_router(requests.router)
app.include_router(sql_agent.router)


@app.get("/health")
def health():
    from src import config
    from src.llm import describe_llm

    agent_db = (config.AGENT_DB_URI or "").strip()
    dialect = None
    if agent_db:
        dialect = agent_db.split(":", 1)[0]
    return {
        "status": "ok",
        "llm": describe_llm(),
        "sql_agent": {
            "configured": bool(agent_db),
            "dialect": dialect,
        },
        "agents": [
            "curriculum",
            "exam_generator",
            "rubric",
            "tutor",
            "sql_agent",
        ],
    }
