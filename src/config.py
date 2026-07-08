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

LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")

# Índices del RAG multi-índice: nombre -> subcarpeta de data/
INDICES = {
    "apuntes": DIR_DATOS / "apuntes",
    "examenes": DIR_DATOS / "examenes",
    "rubricas": DIR_DATOS / "rubricas",
    "curriculo": DIR_DATOS / "curriculo",
}

# Límite de iteraciones del bucle ReAct de cada agente (mitigación de
# riesgos multi-agente: evita bucles infinitos y coste descontrolado).
MAX_ITERACIONES_REACT = 10
