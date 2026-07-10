"""Configuración central del proyecto."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

RAIZ = Path(__file__).resolve().parent.parent
DIR_DATOS = RAIZ / "data"
DIR_STORAGE = RAIZ / "storage"
DIR_CHROMA = DIR_STORAGE / "chroma"
DIR_MEMORIA = DIR_STORAGE / "memoria"
DIR_LOGS = DIR_STORAGE / "logs"

LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")

INDICES_NOMBRES = ("apuntes", "examenes", "rubricas", "curriculo")
INDICES = {
    "apuntes": DIR_DATOS / "apuntes",
    "examenes": DIR_DATOS / "examenes",
    "rubricas": DIR_DATOS / "rubricas",
    "curriculo": DIR_DATOS / "curriculo",
}

MAX_ITERACIONES_REACT = 10

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_VERBOSE = os.getenv("LOG_VERBOSE", "false").lower() in {"1", "true", "yes"}

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "mysql+pymysql://user:pass@localhost:3306/dveloper_gestion_agentes_educacion",
)
JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))
CORS_ORIGINS = [
    o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()
]
