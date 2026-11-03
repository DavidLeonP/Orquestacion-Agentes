"""Guardrails LangChain (middleware) para anclar agentes a la KB de la sesión.

Documentación de referencia:
https://docs.langchain.com/oss/python/langchain/guardrails

Capas:
1. Determinista before_agent: bloquea si la petición no tiene cobertura en la
   base vectorial del usuario (jump_to end).
2. Determinista after_agent: si el agente respondió sin citar fuentes ni usar
   tools RAG cuando la petición pedía contenido, sustituye la salida.
3. PII: redacta emails en entrada/salida (built-in PIIMiddleware).
"""

from __future__ import annotations

from typing import Any

from langchain.agents.middleware import (
    AgentMiddleware,
    AgentState,
    PIIMiddleware,
    hook_config,
)
from langchain.messages import AIMessage
from langgraph.runtime import Runtime

from src.observability.trazas import registrar_evento
from src.rag.cobertura import (
    MENSAJE_FUERA_CONTEXTO,
    evaluar_cobertura,
    indices_para_agente,
)
from src.rag.context import rag_user_id_actual

_MARCAS_SIN_EVIDENCIA = (
    "no consta evidencia",
    "no hay evidencia",
    "base documental no contiene",
    "no puedo atender esta petición",
    "fuera de contexto",
    "sin resultados en la base documental",
)


def _texto_mensaje(msg) -> str:
    content = getattr(msg, "content", "") or ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        partes = []
        for p in content:
            if isinstance(p, str):
                partes.append(p)
            elif isinstance(p, dict) and p.get("type") == "text":
                partes.append(str(p.get("text", "")))
        return " ".join(partes)
    return str(content)


class GroundingGuardrailMiddleware(AgentMiddleware):
    """Before/after agent: exige anclaje a la KB vectorial de la sesión."""

    def __init__(self, agente: str, *, indices: tuple[str, ...] | None = None):
        super().__init__()
        self.agente = agente
        self.indices = indices or indices_para_agente(agente)

    @hook_config(can_jump_to=["end"])
    def before_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        messages = state.get("messages") or []
        if not messages:
            return None
        first = messages[0]
        if getattr(first, "type", None) != "human":
            return None
        consulta = _texto_mensaje(first).strip()
        if not consulta:
            return None

        try:
            cobertura = evaluar_cobertura(consulta, self.indices)
        except Exception as exc:  # noqa: BLE001 - no tumbar el agente si falla el guardrail
            registrar_evento(
                "guardrail_error",
                capa="before_agent",
                agente=self.agente,
                error=str(exc)[:300],
            )
            return None

        if cobertura.suficiente:
            return None

        registrar_evento(
            "guardrail_bloqueado",
            capa="before_agent",
            agente=self.agente,
            motivo=cobertura.motivo,
            score=round(cobertura.score, 4),
        )
        return {
            "messages": [
                {
                    "role": "assistant",
                    "content": cobertura.mensaje_rechazo(),
                }
            ],
            "jump_to": "end",
        }

    @hook_config(can_jump_to=["end"])
    def after_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        # Sin sesión RAG (tests/CLI) no reescribimos la salida.
        if rag_user_id_actual() is None:
            return None

        messages = state.get("messages") or []
        if not messages:
            return None

        last = messages[-1]
        if not isinstance(last, AIMessage):
            return None
        texto = _texto_mensaje(last)
        if not texto.strip():
            return None

        # Ya declaró falta de evidencia: no reescribimos.
        low = texto.lower()
        if any(m in low for m in _MARCAS_SIN_EVIDENCIA):
            return None

        uso_tools = any(
            isinstance(m, AIMessage) and getattr(m, "tool_calls", None) for m in messages
        )
        cita_fuentes = "fuentes consultadas" in low or "[fuente:" in low
        if uso_tools and cita_fuentes:
            return None

        # Respuesta final sin tools ni citas → inventó o ignoró el grounding.
        if not uso_tools or not cita_fuentes:
            registrar_evento(
                "guardrail_bloqueado",
                capa="after_agent",
                agente=self.agente,
                uso_tools=uso_tools,
                cita_fuentes=cita_fuentes,
            )
            last.content = (
                MENSAJE_FUERA_CONTEXTO
                + " La respuesta generada no quedó anclada a fuentes de la "
                "base documental de la sesión, así que se ha descartado."
            )
        return None


def middleware_guardrails(agente: str) -> list:
    """Stack de guardrails para `create_agent` (orden: grounding → PII).

    Una sola instancia de PIIMiddleware: create_agent rechaza duplicados de clase.
    """
    return [
        GroundingGuardrailMiddleware(agente),
        PIIMiddleware(
            "email",
            strategy="redact",
            apply_to_input=True,
            apply_to_output=True,
        ),
    ]
