"""Evalúa el orquestador sobre un conjunto de eval/ con un juez externo.

Llama al LLM real (perfil de .env) y lee la KB del usuario en MySQL. Se detiene
en el HITL: no aprueba nada ni escribe memoria de casos.

Uso:
  python scripts/evaluar.py --conjunto prueba [--limite 3]
  python scripts/evaluar.py --calibrar     # juez interno vs. decisión del docente (sin LLM)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langgraph.checkpoint.memory import MemorySaver

from src.config import DIR_METRICS, JUEZ_MODEL
from src.db.models import Approval
from src.db.session import SessionLocal
from src.evaluation.corrida import (
    calibrar,
    cargar_conjunto,
    correr,
    metricas,
    promedios,
    user_id_por_email,
)
from src.evaluation.juez import juzgar
from src.llm import describe_llm
from src.memory import mysql_store as mem
from src.orchestrator.graph import construir_grafo

METRICAS = ["agente_ok", "recall_fuentes", "cumple_reglas", "juez_puntaje", "juez_paso",
            "intentos", "tokens", "segundos"]


def evaluar(conjunto: str, email: str, limite: int | None) -> None:
    user_id = user_id_por_email(email)
    modelo = describe_llm()
    if not JUEZ_MODEL:
        print("AVISO: JUEZ_MODEL no definido; el juez es el mismo modelo que el generador.")
    app = construir_grafo(checkpointer=MemorySaver(), memory_backend=mem)
    filas = []
    for item in cargar_conjunto(conjunto)[:limite]:
        try:
            r = correr(app, item, user_id)
        except Exception as exc:  # noqa: BLE001 - la fila queda con error y el conjunto sigue
            filas.append({"id": item["id"], "tipo": item["tipo"], "error": str(exc)[:300]})
            print(f"[{item['id']}] ERROR: {exc}")
            continue
        juicio = juzgar(item["peticion"], r["respuesta"], item["referencia"])
        filas.append({"tipo": item["tipo"], **r, **metricas(item, r, juicio), "motivo_juez": juicio.motivo})
        f = filas[-1]
        print(f"[{f['id']}] agente={f['agente']} ok={f['agente_ok']} reglas={f['cumple_reglas']} "
              f"juez={f['juez_puntaje']:.2f} intentos={f['intentos']} tokens={f['tokens']} {f['segundos']}s")
    resumen = {"conjunto": conjunto, "modelo": modelo, "juez": JUEZ_MODEL or modelo["llm_model"],
               "n": len(filas), "errores": sum("error" in f for f in filas),
               **promedios(filas, METRICAS)}
    DIR_METRICS.mkdir(parents=True, exist_ok=True)
    ruta = DIR_METRICS / f"eval_{conjunto}_{datetime.now():%Y%m%d_%H%M%S}.json"
    ruta.write_text(json.dumps({"resumen": resumen, "filas": filas}, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    print(json.dumps(resumen, ensure_ascii=False, indent=1))
    print(f"Detalle: {ruta}")


def calibrar_juez() -> None:
    db = SessionLocal()
    try:
        decididas = db.query(Approval).filter(Approval.decision.in_(["aprobado", "rechazado"])).all()
        # Solo veredictos del Rubric Agent: los rechazos deterministas no son del juez LLM
        pares = [("VEREDICTO: APROBADO" in a.veredicto.upper(), a.decision == "aprobado")
                 for a in decididas if "(revisión automática)" not in a.veredicto]
    finally:
        db.close()
    print("Juez LLM (Rubric Agent) vs. docente:", calibrar(pares))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    # entrenamiento no se evalúa: es de scripts/entrenar_reglas.py
    p.add_argument("--conjunto", default="prueba", choices=["prueba", "reservado"])
    p.add_argument("--email", default="demo@instituto.local")
    p.add_argument("--limite", type=int)
    p.add_argument("--calibrar", action="store_true")
    a = p.parse_args()
    calibrar_juez() if a.calibrar else evaluar(a.conjunto, a.email, a.limite)
