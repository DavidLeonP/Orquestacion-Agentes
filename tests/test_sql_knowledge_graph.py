"""Grafo de conocimiento del SQL Agent (sin red)."""

from __future__ import annotations

from src.sql_agent.knowledge_graph import (
    cargar_knowledge_graph,
    invalidar_cache_kg,
    render_contexto_esquema,
    system_prompt_query_gen,
)
from src.sql_agent.prompts import QUERY_GEN_SYSTEM


def test_kg_carga_entidades_y_relaciones():
    invalidar_cache_kg()
    kg = cargar_knowledge_graph()
    assert kg is not None
    ids = {e["id"] for e in kg["entidades"]}
    assert {"estudiantes", "calificaciones", "promedios_periodo", "ofertas"} <= ids
    assert len(kg["relaciones"]) >= 10


def test_contexto_incluye_joins_y_reglas():
    ctx = render_contexto_esquema()
    assert "promedios_periodo" in ctx
    assert "JOIN" in ctx or "via" in ctx.lower() or "=" in ctx
    assert "Reglas anti-alucinación" in ctx
    assert "alumnos" not in ctx.split("Tablas y significado:")[0]  # no promover legado


def test_system_prompt_concatena_base_y_kg():
    full = system_prompt_query_gen(QUERY_GEN_SYSTEM)
    assert "ProponerConsultaSQL" in full
    assert "GRAFO DE CONOCIMIENTO" in full
    assert "0-10" in full or "0 a 10" in full
