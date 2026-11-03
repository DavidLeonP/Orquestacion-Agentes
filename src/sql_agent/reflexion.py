"""Reflexion del SQL Agent (espejo de `src/orchestrator/reflexion.py`).

Roles (Shinn et al., 2023):
- Actor: `query_gen` (propone SQL / respuesta).
- Evaluador: `verificar_respuesta` (reglas deterministas) + LLM opcional.
- Auto-reflexión: nodo `reflexionar` del grafo → lección en estado.
- HITL: si hay duda semántica, `aclaracion_humana` (interrupt) y se archiva
  en Chroma (`clarificaciones_sql`).
"""

from __future__ import annotations

import re
from typing import Any

from src.agents.schemas import Reflexion
from src.config import MAX_SQL_AGENT_VALIDACIONES
from src.sql_agent.schemas import VeredictoSql

# Frases temporales relativas que suelen requerir `periodos`, no `anio_ingreso`.
_TEMPORAL_RELATIVO = re.compile(
    r"\b(a[nñ]o\s+pasado|semestre\s+pasado|periodo\s+pasado|"
    r"[uú]ltimo\s+(a[nñ]o|periodo|semestre|ciclo)|"
    r"el\s+curso\s+pasado|la\s+temporada\s+pasada)\b",
    re.IGNORECASE,
)
_ANIO_INGRESO = re.compile(r"\banio_ingreso\b", re.IGNORECASE)
_MATRICUL = re.compile(r"\bmatricul", re.IGNORECASE)
_INGRESO_COHORTE = re.compile(
    r"\b(ingres(?:aron|ó|aron|a)|cohorte|nuevo\s+ingreso|primer\s+a[nñ]o)\b",
    re.IGNORECASE,
)


def extraer_peticion(messages: list[Any]) -> str:
    for m in messages:
        role = getattr(m, "type", None) or getattr(m, "role", None)
        if role in {"human", "user"}:
            content = getattr(m, "content", "") or ""
            if isinstance(content, str) and content.strip():
                return content.strip()
    return ""


def extraer_submit(messages: list[Any]) -> tuple[str, str | None]:
    """Último SubmitFinalAnswer → (final_answer, tool_call_id)."""
    for m in reversed(messages):
        for tc in getattr(m, "tool_calls", None) or []:
            if tc.get("name") == "SubmitFinalAnswer":
                args = tc.get("args") or {}
                return str(args.get("final_answer") or ""), tc.get("id")
    return "", None


def extraer_ultimo_sql(messages: list[Any]) -> str:
    """Última query propuesta/ejecutada (ProponerConsultaSQL o db_query_tool)."""
    for m in reversed(messages):
        for tc in getattr(m, "tool_calls", None) or []:
            if tc.get("name") in {"ProponerConsultaSQL", "db_query_tool", "sql_db_query"}:
                q = (tc.get("args") or {}).get("query")
                if q:
                    return str(q)
    return ""


def verificar_respuesta(
    peticion: str,
    respuesta: str,
    sql: str,
    *,
    clarificaciones: list[str] | None = None,
) -> VeredictoSql:
    """Incumplimientos comprobables sin LLM. Lista vacía de motivos ⇒ OK."""
    motivos: list[str] = []
    necesita = False
    pregunta_aclaracion = ""

    pet = (peticion or "").strip()
    resp = (respuesta or "").strip()
    sql_l = sql or ""

    if not resp:
        return VeredictoSql(
            aprobado=False,
            motivos=["La respuesta final está vacía."],
            resumen="Sin respuesta",
            etapa="determinista",
        )

    # Caso canónico: «matricul… el año pasado» filtrado por anio_ingreso.
    temporal = bool(_TEMPORAL_RELATIVO.search(pet))
    habla_matricula = bool(_MATRICUL.search(pet))
    pide_cohorte = bool(_INGRESO_COHORTE.search(pet))
    usa_ingreso = bool(_ANIO_INGRESO.search(sql_l))

    if temporal and habla_matricula and usa_ingreso and not pide_cohorte:
        motivos.append(
            "La pregunta pide matrículas en un periodo relativo («año pasado») pero "
            "el SQL filtra por estudiantes.anio_ingreso (cohorte de ingreso). "
            "Debe filtrar via matriculas → ofertas → periodos."
        )
        necesita = True
        pregunta_aclaracion = (
            "Cuando dices «año pasado», ¿te refieres al último periodo académico "
            "en la base (p. ej. 2024-2025 vía matriculas→ofertas→periodos) o a la "
            "cohorte de ingreso (estudiantes.anio_ingreso)?"
        )

    # Si ya hay aclaración en memoria que corrige anio_ingreso y aun así se usó:
    if usa_ingreso and clarificaciones:
        blob = "\n".join(clarificaciones).lower()
        if "anio_ingreso" in blob and ("no uses" in blob or "no usar" in blob):
            if "Ignoró una aclaración ya aprendida" not in " ".join(motivos):
                motivos.append(
                    "Ignoró una aclaración ya aprendida: no usar anio_ingreso para "
                    "matrículas por periodo relativo."
                )

    if motivos:
        return VeredictoSql(
            aprobado=False,
            necesita_aclaracion=necesita,
            motivos=motivos,
            pregunta_aclaracion=pregunta_aclaracion,
            resumen=motivos[0],
            etapa="determinista",
        )
    return VeredictoSql(
        aprobado=True,
        motivos=[],
        resumen="Validación determinista OK",
        etapa="determinista",
    )


def prompt_reflexion_sql(
    peticion: str,
    respuesta: str,
    sql: str,
    motivos: list[str],
    previas: list[str],
) -> str:
    return (
        "Ayudas al SQL Agent a aprender de un intento rechazado.\n\n"
        f"PETICIÓN:\n{peticion}\n\n"
        f"SQL EJECUTADO:\n{sql or '(ninguno)'}\n\n"
        f"RESPUESTA RECHAZADA:\n{respuesta}\n\n"
        "MOTIVOS DEL RECHAZO:\n" + "\n".join(f"- {m}" for m in motivos) + "\n\n"
        "LECCIONES PREVIAS:\n" + ("\n".join(previas) or "(ninguna)") + "\n\n"
        "Diagnostica el error semántico o de esquema (filtro incorrecto, JOIN "
        "faltante, confusión anio_ingreso vs periodos, alucinación de tablas…) y "
        "propón un plan concreto: qué ProponerConsultaSQL escribir y qué tablas "
        "usar. No repitas lecciones previas. En regla_general escribe una regla "
        "reutilizable para OTRAS consultas SQL, sin datos de esta petición."
    )


def prompt_veredicto_llm(
    peticion: str,
    respuesta: str,
    sql: str,
    motivos_det: list[str],
) -> str:
    return (
        "Eres el evaluador del SQL Agent académico. Decide si la respuesta es "
        "coherente con la pregunta y el SQL, o si hace falta aclaración humana.\n\n"
        f"PETICIÓN:\n{peticion}\n\n"
        f"SQL:\n{sql or '(ninguno)'}\n\n"
        f"RESPUESTA:\n{respuesta}\n\n"
        "MOTIVOS DETERMINISTAS (si hay):\n"
        + ("\n".join(f"- {m}" for m in motivos_det) or "(ninguno)")
        + "\n\n"
        "Marca necesita_aclaracion=true solo si la pregunta es ambigua (fechas "
        "relativas, filtros poco claros) y no puedes resolverla sin el docente. "
        "Si el SQL claramente confunde conceptos (p. ej. anio_ingreso vs periodo "
        "de matrícula), aprobado=false. Si todo cuadra, aprobado=true."
    )


def leccion(numero: int, reflexion: Reflexion) -> str:
    return f"Intento SQL {numero}: {reflexion.diagnostico} Plan: {reflexion.plan}"


def siguiente_paso_sql(veredicto: VeredictoSql, intentos: int) -> str:
    """Tras validar: END / aclaracion_humana / reflexionar."""
    if veredicto.aprobado:
        return "emitir_respuesta"
    if veredicto.necesita_aclaracion and intentos >= 1:
        # Tras al menos un rechazo, o de inmediato si el determinista pide aclaración
        return "aclaracion_humana"
    if intentos >= MAX_SQL_AGENT_VALIDACIONES:
        # Agotados: si aún hay duda, pedir humano; si no, emitir lo que haya
        if veredicto.necesita_aclaracion:
            return "aclaracion_humana"
        return "emitir_respuesta"
    return "reflexionar"


def bloque_memoria(clarificaciones: list[str], lecciones: list[str]) -> str:
    partes: list[str] = []
    if clarificaciones:
        partes.append(
            "ACLARACIONES APRENDIDAS (cúmplelas; vienen de docentes / casos canónicos):\n"
            + "\n---\n".join(clarificaciones)
        )
    if lecciones:
        partes.append(
            "LECCIONES DE ESTA PETICIÓN (intentos rechazados):\n"
            + "\n".join(f"- {l}" for l in lecciones)
        )
    return ("\n\n" + "\n\n".join(partes)) if partes else ""
