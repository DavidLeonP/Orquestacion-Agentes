"""Ejecuta el orquestador sobre un conjunto de eval/ y calcula métricas.

Lo comparten scripts/evaluar.py y scripts/entrenar_reglas.py. La corrida se
detiene en el HITL (no reanuda), así que la memoria de casos es de solo lectura.
"""

from __future__ import annotations

import json
import time
import uuid

from langchain_core.callbacks import get_usage_metadata_callback

from src.config import DIR_EVAL
from src.contexto_usuario import contexto_usuario
from src.db.models import User
from src.db.session import SessionLocal
from src.orchestrator.reflexion import mejor_intento
from src.rag.context import iniciar_evidencia


def user_id_por_email(email: str) -> int:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if user is None:
            raise SystemExit(f"Usuario {email} no existe (python scripts/seed_demo_kb.py)")
        return user.id
    finally:
        db.close()


def cargar_conjunto(nombre: str) -> list[dict]:
    lineas = (DIR_EVAL / f"{nombre}.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(l) for l in lineas if l.strip()]


def correr(app, item: dict, user_id: int) -> dict:
    """Una petición hasta END o hasta el interrupt HITL."""
    config = {"configurable": {"thread_id": f"eval-{uuid.uuid4()}"}}
    vistas = iniciar_evidencia()  # fuentes de tutor, rubric y curriculum
    inicio, hitl = time.perf_counter(), None
    with contexto_usuario(user_id), get_usage_metadata_callback() as uso:
        for chunk in app.stream(
            {"peticion": item["peticion"], "rol_usuario": item["rol"]},
            config=config,
            stream_mode="updates",
        ):
            if "__interrupt__" in chunk:
                hitl = chunk["__interrupt__"][0].value
        estado = app.get_state(config).values
    intentos = estado.get("intentos", [])
    elegido = mejor_intento(intentos) if intentos else None
    return {
        "id": item["id"],
        "agente": estado.get("agente_destino"),
        "respuesta": hitl["borrador"] if hitl else estado.get("respuesta_final", ""),
        # Exámenes: las fuentes del intento entregado (no las del Rubric Agent ni de otro intento)
        "fuentes": sorted(set(elegido["fuentes"] if elegido else vistas)),
        "intentos": len(intentos) or None,
        "errores_reglas": elegido["errores"] if elegido else None,
        "aprobado_rubric": elegido["veredicto"]["aprobado"] if elegido else None,
        "reglas_nuevas": estado.get("reglas_nuevas", []),
        "tokens": sum(u.get("total_tokens", 0) for u in uso.usage_metadata.values()),
        "segundos": round(time.perf_counter() - inicio, 1),
    }


def metricas(item: dict, r: dict, juicio) -> dict:
    """Deterministas (sin costo) + las del juez."""
    esperadas = item.get("fuentes_esperadas", [])
    return {
        "agente_ok": r["agente"] == item["agente_esperado"],
        "recall_fuentes": (
            sum(any(e in f for f in r["fuentes"]) for e in esperadas) / len(esperadas)
            if esperadas else None
        ),
        "cumple_reglas": r["errores_reglas"] == [] if r["errores_reglas"] is not None else None,
        "juez_puntaje": juicio.puntaje,
        "juez_paso": juicio.paso,
    }


def promedios(filas: list[dict], claves: list[str]) -> dict:
    """Media de cada métrica ignorando los None (p. ej. cumple_reglas fuera de exámenes)."""
    salida = {}
    for k in claves:
        valores = [float(f[k]) for f in filas if f.get(k) is not None]
        salida[k] = round(sum(valores) / len(valores), 3) if valores else None
    return salida


def calibrar(pares: list[tuple[bool, bool]]) -> dict:
    """(juez aprobó, docente aprobó) → matriz de confusión del juez contra el HITL."""
    return {
        "aciertos": sum(j == d for j, d in pares),
        "falsos_pass": sum(j and not d for j, d in pares),
        "falsos_fail": sum(d and not j for j, d in pares),
        "total": len(pares),
    }
