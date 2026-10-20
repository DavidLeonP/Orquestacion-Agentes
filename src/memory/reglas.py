"""Manual de reglas aprendidas (Reflexion como entrenamiento, notebook §5B.6).

`scripts/entrenar_reglas.py` lo escribe; el grafo lo lee al construirse.
Archivo JSON en storage/ con una entrada por agente:
{"exam_generator": {"modelo", "version", "reglas", "creado", ...}}.
Las reglas solo se usan con el modelo con el que se aprendieron.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from src.config import RUTA_REGLAS
from src.llm import get_selection

logger = logging.getLogger("orquestacion.memoria")


def _leer() -> dict:
    if not RUTA_REGLAS.exists():
        return {}
    try:
        return json.loads(RUTA_REGLAS.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:  # un manual corrupto no debe tumbar la API
        logger.warning("Manual de reglas ilegible (%s): se ignora", exc)
        return {}


def cargar(agente: str) -> list[str]:
    manual = _leer().get(agente)
    if not manual:
        return []
    modelo = get_selection().llm_model
    if manual.get("modelo") != modelo:
        logger.info("Reglas de %s aprendidas con %s; el modelo activo es %s: no se usan",
                    agente, manual.get("modelo"), modelo)
        return []
    return manual["reglas"]


def guardar(agente: str, reglas: list[str], **meta) -> dict:
    todo = _leer()
    entrada = {
        "modelo": get_selection().llm_model,
        "version": todo.get(agente, {}).get("version", 0) + 1,
        "reglas": reglas,
        "creado": datetime.now(timezone.utc).isoformat(),
        **meta,
    }
    todo[agente] = entrada
    RUTA_REGLAS.parent.mkdir(parents=True, exist_ok=True)
    RUTA_REGLAS.write_text(json.dumps(todo, ensure_ascii=False, indent=2), encoding="utf-8")
    return entrada
