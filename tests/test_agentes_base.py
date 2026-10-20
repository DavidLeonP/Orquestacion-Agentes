"""Fábrica de agentes (langchain.agents.create_agent) con un chat model falso, sin red."""

from __future__ import annotations

import itertools

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool

from src.agents import base as agents_base
from src.config import MAX_ITERACIONES_REACT


class ChatGrabador(GenericFakeChatModel):
    """Devuelve los mensajes del guion y guarda lo que recibe en cada llamada."""

    recibidos: list = []

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.recibidos.append(list(messages))
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


@pytest.fixture
def eventos(monkeypatch):
    registro: list[tuple[str, dict]] = []
    monkeypatch.setattr(agents_base, "registrar_evento", lambda tipo, **k: registro.append((tipo, k)))
    return registro


def _agente(monkeypatch, mensajes, tools):
    llm = ChatGrabador(messages=iter(mensajes), recibidos=[])
    monkeypatch.setattr(agents_base, "get_chat_model", lambda **k: llm)
    return agents_base.crear_agente("prueba", "Eres un agente de prueba.", tools), llm


@tool
def buscar_rota(consulta: str) -> str:
    """Tool que siempre falla (p. ej. MySQL caído)."""
    raise ConnectionError("MySQL caído")


@tool
def buscar_ok(consulta: str) -> str:
    """Tool que responde."""
    return f"[fuente: ok.txt] {consulta}"


def _llamada(nombre, id_):
    return AIMessage(content="", tool_calls=[{"name": nombre, "args": {"consulta": "q"}, "id": id_}])


def test_crear_agente_usa_prompt_con_grounding(monkeypatch, eventos):
    agente, llm = _agente(monkeypatch, [AIMessage(content="ok")], [buscar_ok])
    assert agents_base.ejecutar_agente(agente, "hola", "prueba") == "ok"
    sistema = llm.recibidos[0][0]
    assert sistema.type == "system"
    assert "Eres un agente de prueba." in sistema.content
    assert "REGLAS DE GROUNDING" in sistema.content


def test_error_de_tool_vuelve_como_observacion(monkeypatch, eventos):
    agente, llm = _agente(
        monkeypatch,
        [_llamada("buscar_rota", "c1"), AIMessage(content="No consta evidencia suficiente.")],
        [buscar_rota],
    )
    respuesta = agents_base.ejecutar_agente(agente, "Busca algo", "prueba")
    assert respuesta == "No consta evidencia suficiente."
    # El modelo recibió la observación de error en su segunda llamada
    (obs,) = [m for m in llm.recibidos[1] if isinstance(m, ToolMessage)]
    assert obs.status == "error" and obs.tool_call_id == "c1" and obs.name == "buscar_rota"
    assert "Error al ejecutar buscar_rota: ConnectionError" in obs.content
    assert "MySQL caído" not in obs.content  # el detalle va a la traza, no al modelo
    (err,) = [k for t, k in eventos if t == "tool_error"]
    assert err["tool"] == "buscar_rota" and "MySQL caído" in err["error"]
    (fin,) = [k for t, k in eventos if t == "agente_fin"]
    assert fin["tools_usadas"].count("buscar_rota") == 2  # tool_call + ToolMessage


def test_tool_correcta_no_registra_error(monkeypatch, eventos):
    agente, llm = _agente(monkeypatch, [_llamada("buscar_ok", "c1"), AIMessage(content="fin")], [buscar_ok])
    assert agents_base.ejecutar_agente(agente, "x", "prueba") == "fin"
    (obs,) = [m for m in llm.recibidos[1] if isinstance(m, ToolMessage)]
    assert obs.status == "success" and "ok.txt" in obs.content
    assert not [t for t, _ in eventos if t == "tool_error"]


def test_limite_de_iteraciones_devuelve_mensaje_controlado(monkeypatch, eventos):
    sin_fin = (_llamada("buscar_ok", f"c{i}") for i in itertools.count())
    agente, llm = _agente(monkeypatch, sin_fin, [buscar_ok])
    respuesta = agents_base.ejecutar_agente(agente, "x", "prueba")
    assert respuesta.startswith(f"No pude completar la tarea en {MAX_ITERACIONES_REACT} iteraciones")
    (fin,) = [k for t, k in eventos if t == "agente_fin"]
    assert fin["limite_iteraciones"] is True
    # recursion_limit = 2 * MAX + 5 -> el modelo se llama unas MAX veces, no sin fin
    assert MAX_ITERACIONES_REACT <= len(llm.recibidos) <= MAX_ITERACIONES_REACT + 3


def test_tokens_se_suman_entre_iteraciones(monkeypatch, eventos):
    uso = {"input_tokens": 3, "output_tokens": 4, "total_tokens": 7}
    primera = _llamada("buscar_ok", "c1")
    primera.usage_metadata = uso
    agente, _ = _agente(monkeypatch, [primera, AIMessage(content="fin", usage_metadata=uso)], [buscar_ok])
    assert agents_base.ejecutar_agente(agente, "x", "prueba") == "fin"
    (fin,) = [k for t, k in eventos if t == "agente_fin"]
    assert fin["tokens_in"] == 6 and fin["tokens_out"] == 8 and fin["iteraciones_llm"] == 2
    assert fin["cita_fuentes"] is False


def test_ejecutar_agente_respuesta_no_str(monkeypatch, eventos):
    agente, _ = _agente(monkeypatch, [AIMessage(content=[{"type": "text", "text": "hola"}])], [buscar_ok])
    assert "hola" in agents_base.ejecutar_agente(agente, "x", "prueba")


def _correr_n_tools(monkeypatch, n_tools):
    guion = [_llamada("buscar_ok", f"c{i}") for i in range(n_tools)] + [AIMessage(content="fin")]
    agente, _ = _agente(monkeypatch, guion, [buscar_ok])
    return agents_base.ejecutar_agente(agente, "x", "prueba")


def test_mas_de_max_iteraciones_da_texto_controlado(monkeypatch, eventos):
    assert _correr_n_tools(monkeypatch, MAX_ITERACIONES_REACT + 1).startswith("No pude completar")


def test_menos_de_max_iteraciones_responde(monkeypatch, eventos):
    assert _correr_n_tools(monkeypatch, MAX_ITERACIONES_REACT - 1) == "fin"


# BUG (base.py, recursion_limit = 2*MAX+1): medido con create_agent + middleware,
# MAX iteraciones con tool + la respuesta final necesitan 2*MAX+3 super-steps
# (con MAX=10: 9 tools pasan, 10 ya dan el texto controlado). Con el +5 anterior
# cabían 11. Corrección sugerida: recursion_limit = 2 * MAX_ITERACIONES_REACT + 3.
def test_exactamente_max_iteraciones_responde(monkeypatch, eventos):
    assert _correr_n_tools(monkeypatch, MAX_ITERACIONES_REACT) == "fin"


# Regresión (base.py, error_como_observacion): antes `except Exception` se tragaba
# GraphInterrupt y un interrupt() en una tool acababa como ToolMessage de error.
def test_interrupt_en_tool_no_se_convierte_en_error(monkeypatch, eventos):
    from typing import TypedDict

    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import interrupt

    @tool
    def pedir_confirmacion(consulta: str) -> str:
        """Pide confirmación humana."""
        return str(interrupt({"pregunta": consulta}))

    agente, _ = _agente(monkeypatch, [_llamada("pedir_confirmacion", "c1"), AIMessage(content="fin")],
                        [pedir_confirmacion])

    class S(TypedDict, total=False):
        r: str

    g = StateGraph(S)
    g.add_node("agente", lambda s: {"r": agents_base.ejecutar_agente(agente, "x", "prueba")})
    g.add_edge(START, "agente")
    g.add_edge("agente", END)
    app = g.compile(checkpointer=MemorySaver())
    salida = app.invoke({}, {"configurable": {"thread_id": "i1"}})
    assert "__interrupt__" in salida
    assert not [t for t, _ in eventos if t == "tool_error"]
