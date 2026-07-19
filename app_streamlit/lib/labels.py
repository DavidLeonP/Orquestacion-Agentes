"""Etiquetas legibles para estados, agentes, índices y navegación."""

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

NAV_DESCRIPTIONS: dict[str, str] = {
    "pages/1_Conocimiento.py": "Sube y gestiona apuntes, exámenes y rúbricas.",
    "pages/2_Asistente.py": "Haz una pregunta o pide generar material.",
    "pages/3_Historial.py": "Revisa peticiones anteriores y su resultado.",
    "pages/4_Aprobaciones.py": "Aprueba o rechaza borradores de examen.",
}

STATUS_LABELS: dict[str, str] = {
    "running": "En proceso",
    "waiting_approval": "Pendiente de aprobación",
    "completed": "Completada",
    "failed": "Falló",
}

STATUS_EMOJI: dict[str, str] = {
    "running": "🔄",
    "waiting_approval": "⏳",
    "completed": "✅",
    "failed": "❌",
}

DOC_STATUS_LABELS: dict[str, str] = {
    "pending": "Pendiente de indexar",
    "ready": "Listo",
    "indexed": "Indexado",
    "error": "Error",
    "failed": "Error",
    "processing": "Indexando…",
}

INDICE_LABELS: dict[str, str] = {
    "apuntes": "Apuntes",
    "examenes": "Exámenes",
    "rubricas": "Rúbricas",
    "curriculo": "Currículo",
}

INDICE_HINTS: dict[str, str] = {
    "apuntes": "Material de estudio y explicaciones.",
    "examenes": "Exámenes históricos del centro.",
    "rubricas": "Criterios de evaluación.",
    "curriculo": "Unidades y programación oficial.",
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

# Orden aproximado de fases para barra de progreso
PHASE_ORDER: list[str] = [
    "router",
    "exam_generator",
    "curriculum",
    "rubric",
    "tutor",
    "validar",
    "aprobacion_docente",
    "finalizar",
]


def status_label(status: str | None) -> str:
    if not status:
        return "Desconocido"
    return STATUS_LABELS.get(status, status)


def status_badge(status: str | None) -> str:
    if not status:
        return "Desconocido"
    emoji = STATUS_EMOJI.get(status, "•")
    return f"{emoji} {status_label(status)}"


def doc_status_label(status: str | None) -> str:
    if not status:
        return "Desconocido"
    return DOC_STATUS_LABELS.get(status, status.replace("_", " ").title())


def indice_label(indice: str | None) -> str:
    if not indice:
        return "—"
    return INDICE_LABELS.get(indice, indice.title())


def indice_hint(indice: str | None) -> str:
    if not indice:
        return ""
    return INDICE_HINTS.get(indice, "")


def agent_label(agente: str | None) -> str:
    if not agente:
        return "Preparando…"
    return AGENT_LABELS.get(agente, agente.replace("_", " ").title())


def node_hint(nodo: str | None) -> str:
    if not nodo:
        return "Los agentes pueden tardar 1–2 minutos; no está colgado."
    return NODE_HINTS.get(nodo, "Trabajando en tu petición…")


def phase_progress(nodo: str | None, status: str | None) -> float:
    """Progreso aproximado 0–1 según nodo y estado terminal."""
    if status == "completed":
        return 1.0
    if status == "failed":
        return 1.0
    if status == "waiting_approval":
        return 0.9
    if not nodo:
        return 0.05
    try:
        idx = PHASE_ORDER.index(nodo)
    except ValueError:
        return 0.3
    return min(0.85, (idx + 1) / len(PHASE_ORDER))


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
