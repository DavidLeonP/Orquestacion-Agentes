"""Etiquetas legibles para estados, agentes y navegación."""

from __future__ import annotations

from typing import Any

# Orden del menú autenticado (ruta relativa a app_streamlit/)
NAV_ITEMS: list[tuple[str, str, str]] = [
    ("Home.py", "Inicio", "🏠"),
    ("pages/1_Conocimiento.py", "Conocimiento", "📚"),
    ("pages/2_Asistente.py", "Asistente", "💬"),
    ("pages/3_Historial.py", "Historial", "📋"),
    ("pages/4_Aprobaciones.py", "Aprobaciones", "✅"),
]

STATUS_LABELS: dict[str, str] = {
    "running": "En proceso",
    "waiting_approval": "Pendiente de aprobación",
    "completed": "Completada",
    "failed": "Falló",
}

AGENT_LABELS: dict[str, str] = {
    "router": "Clasificando la petición",
    "exam_generator": "Generando el examen",
    "validar": "Validando con la rúbrica",
    "curriculum": "Preparando el plan curricular",
    "rubric": "Diseñando la rúbrica",
    "tutor": "El tutor está respondiendo",
    "aprobacion_docente": "Listo para revisión docente",
    "finalizar": "Redactando la respuesta final",
}

NODE_HINTS: dict[str, str] = {
    "router": "El supervisor decide qué agente debe atenderte.",
    "exam_generator": "Consulta apuntes, exámenes y rúbricas. Puede tardar 30–60 s.",
    "validar": "El agente de rúbrica revisa el borrador.",
    "curriculum": "Organiza sesiones y contenidos del currículo.",
    "rubric": "Propone criterios de evaluación.",
    "tutor": "Responde con base en tu material privado.",
    "finalizar": "Empaqueta la respuesta final.",
}


def status_label(status: str | None) -> str:
    if not status:
        return "Desconocido"
    return STATUS_LABELS.get(status, status)


def agent_label(agente: str | None) -> str:
    if not agente:
        return "Preparando…"
    return AGENT_LABELS.get(agente, agente.replace("_", " ").title())


def node_hint(nodo: str | None) -> str:
    if not nodo:
        return "Los agentes pueden tardar 1–2 minutos; no está colgado."
    return NODE_HINTS.get(nodo, "Trabajando en tu petición…")


def format_llm_badge(health: dict[str, Any] | None) -> tuple[str, str]:
    """Devuelve (título corto, detalle) del modelo activo."""
    if not health:
        return ("API no disponible", "No se pudo leer /health")
    llm = health.get("llm") or {}
    profile = llm.get("profile") or "?"
    model = llm.get("llm_model") or "?"
    provider = llm.get("llm_provider") or "?"
    emb = llm.get("embedding_model") or "?"
    title = f"{provider} · {model}"
    detail = f"Perfil `{profile}` · embeddings `{emb}`"
    return title, detail
