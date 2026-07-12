"""Trazas locales (JSONL) y configuración de LangSmith.

Cada solicitud genera un archivo en storage/logs/<run_id>.jsonl con eventos
estructurados: nodos del grafo, llamadas a agentes, búsquedas RAG y tiempos.

LangSmith se activa con variables de entorno estándar de LangChain; no requiere
código adicional más allá de metadata en el config del grafo.
"""

from __future__ import annotations

import json
import logging
import os
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import DIR_LOGS, LOG_LEVEL, LOG_VERBOSE

_run_id: ContextVar[str | None] = ContextVar("run_id", default=None)
_logger = logging.getLogger("orquestacion")


def configurar_observabilidad() -> None:
    """Configura logging de consola y comprueba LangSmith."""
    nivel = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
    if not _logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")
        )
        _logger.addHandler(handler)
    _logger.setLevel(nivel)

    DIR_LOGS.mkdir(parents=True, exist_ok=True)

    if langsmith_activo():
        _logger.info(
            "LangSmith activo -> proyecto '%s' (https://smith.langchain.com)",
            os.getenv("LANGCHAIN_PROJECT", "default"),
        )
    else:
        _logger.info(
            "LangSmith inactivo. Trazas locales en %s", DIR_LOGS.resolve()
        )


def langsmith_activo() -> bool:
    return (
        os.getenv("LANGCHAIN_TRACING_V2", "").lower() in {"1", "true", "yes"}
        and bool(os.getenv("LANGCHAIN_API_KEY"))
    )


def _ruta_log(run_id: str) -> Path:
    return DIR_LOGS / f"{run_id}.jsonl"


def registrar_evento(tipo: str, **datos: Any) -> None:
    """Escribe un evento JSONL asociado al run_id del contexto actual."""
    run_id = _run_id.get()
    if not run_id:
        return

    evento = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "tipo": tipo,
        **datos,
    }
    with _ruta_log(run_id).open("a", encoding="utf-8") as f:
        f.write(json.dumps(evento, ensure_ascii=False) + "\n")

    if LOG_VERBOSE:
        resumen = {k: v for k, v in datos.items() if k not in {"borrador", "respuesta"}}
        _logger.info("[%s] %s %s", run_id[:8], tipo, resumen)


class TrazasSolicitud:
    """Context manager que delimita una solicitud y su archivo de trazas."""

    def __init__(
        self,
        run_id: str,
        rol: str,
        peticion: str,
        alumno_id: str | None = None,
    ):
        self.run_id = run_id
        self.rol = rol
        self.peticion = peticion
        self.alumno_id = alumno_id
        self._token = None
        self._inicio = 0.0

    def __enter__(self) -> TrazasSolicitud:
        self._token = _run_id.set(self.run_id)
        self._inicio = time.perf_counter()
        registrar_evento(
            "solicitud_inicio",
            rol=self.rol,
            peticion=self.peticion,
            alumno_id=self.alumno_id,
            langsmith=langsmith_activo(),
        )
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        duracion_ms = round((time.perf_counter() - self._inicio) * 1000)
        if exc_type:
            registrar_evento(
                "solicitud_error",
                error=str(exc),
                duracion_ms=duracion_ms,
            )
            _logger.error("Solicitud %s falló: %s", self.run_id[:8], exc)
        else:
            registrar_evento("solicitud_fin", duracion_ms=duracion_ms)
            _logger.info(
                "Solicitud %s completada en %d ms -> %s",
                self.run_id[:8],
                duracion_ms,
                _ruta_log(self.run_id).name,
            )
        if self._token is not None:
            _run_id.reset(self._token)


def config_langgraph(
    run_id: str,
    rol: str,
    peticion: str,
    alumno_id: str | None = None,
) -> dict:
    """Metadata y tags para LangSmith + thread_id del checkpointer."""
    return {
        "configurable": {"thread_id": run_id},
        "run_name": f"{rol}: {peticion[:80]}",
        "tags": ["orquestacion", rol],
        "metadata": {
            "rol": rol,
            "alumno_id": alumno_id or "anonimo",
            "run_id": run_id,
        },
    }


def _truncar(texto: str | None, max_len: int = 200) -> str | None:
    if texto is None:
        return None
    return texto if len(texto) <= max_len else texto[:max_len] + "..."


def resumir_trazas(ultimas: int = 10) -> str:
    """Genera un resumen textual de las últimas solicitudes registradas."""
    if not DIR_LOGS.exists():
        return "No hay trazas. Ejecuta una petición con docente/alumno/demo."

    archivos = sorted(
        DIR_LOGS.glob("*.jsonl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:ultimas]

    if not archivos:
        return "No hay trazas. Ejecuta una petición con docente/alumno/demo."

    lineas = [f"=== Últimas {len(archivos)} solicitudes ===\n"]
    for ruta in archivos:
        eventos = [
            json.loads(l)
            for l in ruta.read_text(encoding="utf-8").splitlines()
            if l.strip()
        ]
        inicio = next((e for e in eventos if e["tipo"] == "solicitud_inicio"), {})
        fin = next((e for e in eventos if e["tipo"] == "solicitud_fin"), {})
        error = next((e for e in eventos if e["tipo"] == "solicitud_error"), None)

        nodos = [e["nodo"] for e in eventos if e["tipo"] == "nodo_grafo"]
        agentes = [e["agente"] for e in eventos if e["tipo"] == "agente_fin"]
        busquedas = [
            f"{e['indice']}({e.get('num_resultados', '?')})"
            for e in eventos
            if e["tipo"] == "rag_busqueda"
        ]
        router = next(
            (e.get("agente_destino") for e in eventos if e["tipo"] == "router"),
            None,
        )

        lineas.append(f"Run: {ruta.stem}")
        lineas.append(f"  Rol: {inicio.get('rol', '?')}")
        lineas.append(f"  Petición: {_truncar(inicio.get('peticion'), 100)}")
        if router:
            lineas.append(f"  Router -> {router}")
        if nodos:
            lineas.append(f"  Nodos: {' -> '.join(nodos)}")
        if agentes:
            lineas.append(f"  Agentes: {', '.join(agentes)}")
        if busquedas:
            lineas.append(f"  RAG: {', '.join(busquedas)}")
        if error:
            lineas.append(f"  ERROR: {error.get('error')}")
        elif fin:
            lineas.append(f"  Duración: {fin.get('duracion_ms', '?')} ms")
        lineas.append(f"  Archivo: {ruta}")
        lineas.append("")

    return "\n".join(lineas)
