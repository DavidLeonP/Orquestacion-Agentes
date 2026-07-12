"""Aplicación FastAPI — Asistente IA Educación."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routers import auth, knowledge, requests
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


@app.get("/health")
def health():
    return {"status": "ok"}
