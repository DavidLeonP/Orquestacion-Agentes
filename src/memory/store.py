"""Memoria de largo plazo (directriz de aprendizaje §4.2).

Tres espacios persistidos en JSON:
- feedback_docente: material aprobado/corregido y observaciones.
- perfil_alumno: progreso y dificultades por alumno (lo usa el Tutor Agent).
- historico_generaciones: material ya generado, para no repetir y mantener estilo.

La memoria de corto plazo (sesión) la gestiona el checkpointer de LangGraph.
"""

import json
from datetime import datetime, timezone

from src.config import DIR_MEMORIA

ESPACIOS = ("feedback_docente", "perfil_alumno", "historico_generaciones")


def _ruta(espacio: str):
    if espacio not in ESPACIOS:
        raise ValueError(f"Espacio de memoria desconocido: {espacio}")
    DIR_MEMORIA.mkdir(parents=True, exist_ok=True)
    return DIR_MEMORIA / f"{espacio}.json"


def leer(espacio: str) -> list[dict]:
    ruta = _ruta(espacio)
    if not ruta.exists():
        return []
    return json.loads(ruta.read_text(encoding="utf-8"))


def guardar(espacio: str, registro: dict) -> None:
    registros = leer(espacio)
    registro["timestamp"] = datetime.now(timezone.utc).isoformat()
    registros.append(registro)
    _ruta(espacio).write_text(
        json.dumps(registros, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def perfil_de_alumno(alumno_id: str) -> str:
    """Resumen textual del perfil de un alumno para inyectar al Tutor Agent."""
    entradas = [r for r in leer("perfil_alumno") if r.get("alumno_id") == alumno_id]
    if not entradas:
        return "Sin historial previo para este alumno."
    lineas = [f"- {r['timestamp'][:10]}: {r.get('nota', '')}" for r in entradas[-5:]]
    return "Historial reciente del alumno:\n" + "\n".join(lineas)
