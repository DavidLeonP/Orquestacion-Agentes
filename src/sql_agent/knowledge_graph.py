"""Grafo de conocimiento del esquema de negocio para el SQL Agent.

Carga `data/sintetica_academica/knowledge_graph.json` (o SQL_AGENT_KG_PATH) y
produce un bloque de contexto que se inyecta en el system prompt de query_gen.
Así el LLM conoce tablas, JOINs y reglas válidas y reduce alucinaciones
(tablas inventadas, columnas inexistentes, escala de notas incorrecta).
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from src import config

logger = logging.getLogger("orquestacion.sql_agent")


def _ruta_kg() -> Path:
    raw = (getattr(config, "SQL_AGENT_KG_PATH", None) or "").strip()
    if raw:
        p = Path(raw)
        return p if p.is_absolute() else config.RAIZ / p
    return config.RAIZ / "data" / "sintetica_academica" / "knowledge_graph.json"


@lru_cache(maxsize=4)
def cargar_knowledge_graph(ruta: str | None = None) -> dict[str, Any] | None:
    path = Path(ruta) if ruta else _ruta_kg()
    if not path.exists():
        logger.warning("Knowledge graph SQL Agent no encontrado: %s", path)
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("No se pudo cargar knowledge graph (%s): %s", path, exc)
        return None


def invalidar_cache_kg() -> None:
    cargar_knowledge_graph.cache_clear()


def render_contexto_esquema(kg: dict[str, Any] | None = None) -> str:
    """Texto compacto para el system prompt (tablas, relaciones, reglas)."""
    kg = kg if kg is not None else cargar_knowledge_graph()
    if not kg:
        return (
            "CONTEXTO DE ESQUEMA: no hay grafo de conocimiento cargado. "
            "Usa únicamente las tablas devueltas por sql_db_list_tables / sql_db_schema. "
            "No inventes tablas ni columnas."
        )

    meta = kg.get("meta") or {}
    lineas = [
        "=== GRAFO DE CONOCIMIENTO DEL ESQUEMA (obligatorio) ===",
        f"Universidad/contexto: {meta.get('universidad', 'BD de negocio académica')}",
        f"Escala de notas: {meta.get('escala_notas', '0-10')}",
        "",
        "Tablas y significado:",
    ]
    for e in kg.get("entidades") or []:
        cols = ", ".join(e.get("columnas_clave") or [])
        lineas.append(f"- {e['id']}: {e.get('descripcion', '')} Columnas clave: {cols}.")

    lineas.append("")
    lineas.append("Relaciones (JOIN):")
    for r in kg.get("relaciones") or []:
        lineas.append(
            f"- {r.get('desde')} → {r.get('hacia')} ({r.get('cardinalidad', '')}): {r.get('via')}"
        )

    lineas.append("")
    lineas.append("Reglas anti-alucinación:")
    for regla in kg.get("reglas_consulta") or []:
        lineas.append(f"- {regla}")

    ejemplos = kg.get("preguntas_ejemplo") or []
    if ejemplos:
        lineas.append("")
        lineas.append("Ejemplos de intención → tablas:")
        for ej in ejemplos[:6]:
            tabs = ", ".join(ej.get("tablas") or []) or "(ninguna / fuera de esquema)"
            lineas.append(f"- «{ej.get('pregunta', '')}» → [{tabs}]")

    lineas.append("=== FIN GRAFO DE CONOCIMIENTO ===")
    return "\n".join(lineas)


def system_prompt_query_gen(base_prompt: str, kg: dict[str, Any] | None = None) -> str:
    return f"{base_prompt.rstrip()}\n\n{render_contexto_esquema(kg)}"
