"""Guardrails LangChain (middleware) de grounding a la KB de sesión."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from src.agents.guardrails import GroundingGuardrailMiddleware
from src.rag import context as rag_context
from src.rag.cobertura import CoberturaKB, MENSAJE_FUERA_CONTEXTO


class _Runtime:
    pass


def test_before_agent_bloquea_sin_cobertura(monkeypatch):
    mw = GroundingGuardrailMiddleware("exam_generator")
    monkeypatch.setattr(
        "src.agents.guardrails.evaluar_cobertura",
        lambda *a, **k: CoberturaKB(suficiente=False, score=0.01, motivo="bajo"),
    )
    out = mw.before_agent(
        {"messages": [HumanMessage(content="colores del renacimiento")]},
        _Runtime(),
    )
    assert out is not None
    assert out["jump_to"] == "end"
    assert MENSAJE_FUERA_CONTEXTO.split(":")[0] in out["messages"][0]["content"]


def test_before_agent_permite_con_cobertura(monkeypatch):
    mw = GroundingGuardrailMiddleware("tutor")
    monkeypatch.setattr(
        "src.agents.guardrails.evaluar_cobertura",
        lambda *a, **k: CoberturaKB(suficiente=True, score=0.8),
    )
    assert (
        mw.before_agent({"messages": [HumanMessage(content="ley de Ohm")]}, _Runtime())
        is None
    )


def test_after_agent_sin_sesion_no_reescribe():
    mw = GroundingGuardrailMiddleware("tutor")
    msg = AIMessage(content="respuesta inventada sin fuentes")
    assert mw.after_agent({"messages": [HumanMessage(content="x"), msg]}, _Runtime()) is None
    assert msg.content == "respuesta inventada sin fuentes"


def test_after_agent_con_sesion_descarta_sin_fuentes():
    mw = GroundingGuardrailMiddleware("tutor")
    token = rag_context.set_rag_user_id(7)
    try:
        msg = AIMessage(content="Los artistas del renacimiento usaban temple.")
        mw.after_agent({"messages": [HumanMessage(content="x"), msg]}, _Runtime())
        assert "base documental" in msg.content.lower() or "sesión" in msg.content.lower()
    finally:
        rag_context.reset_rag_user_id(token)


def test_after_agent_respeta_respuesta_con_tools_y_fuentes():
    mw = GroundingGuardrailMiddleware("exam_generator")
    token = rag_context.set_rag_user_id(7)
    try:
        llamada = AIMessage(
            content="",
            tool_calls=[{"name": "buscar_apuntes", "args": {"consulta": "ohm"}, "id": "1"}],
        )
        final = AIMessage(
            content="Examen...\n\nFuentes consultadas:\n- apuntes.pdf"
        )
        mw.after_agent(
            {"messages": [HumanMessage(content="x"), llamada, final]},
            _Runtime(),
        )
        assert final.content.startswith("Examen")
    finally:
        rag_context.reset_rag_user_id(token)
