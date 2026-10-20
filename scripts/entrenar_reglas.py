"""Entrena el manual de reglas del Exam Generator (Reflexion como entrenamiento).

1. Corre el orquestador sobre eval/entrenamiento.jsonl (nunca se evalúa con él).
2. Un oráculo (juez que SÍ ve la referencia) aprueba o reprueba cada examen; si
   reprueba, el Reflector escribe una regla general. Se suman las reglas generales
   que dejó la reflexión dentro del grafo.
3. Se consolidan con el manual vigente en <= 8 reglas y se guardan versionadas en
   storage/reglas_aprendidas.json. El grafo las lee al construirse (reiniciar la API).

Uso:
  python scripts/entrenar_reglas.py [--limite 3]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langgraph.checkpoint.memory import MemorySaver

from src.agents.base import invocar_estructurado
from src.agents.schemas import Reflexion
from src.config import EVAL_MODEL
from src.evaluation.corrida import cargar_conjunto, correr, user_id_por_email
from src.evaluation.juez import consolidar_reglas, juzgar
from src.memory import mysql_store as mem
from src.memory import reglas as manual_reglas
from src.orchestrator.graph import construir_grafo
from src.orchestrator.reflexion import prompt_reflexion

AGENTE = "exam_generator"


def entrenar(email: str, limite: int | None) -> None:
    user_id = user_id_por_email(email)
    app = construir_grafo(checkpointer=MemorySaver(), memory_backend=mem)
    items = [i for i in cargar_conjunto("entrenamiento") if i["agente_esperado"] == AGENTE][:limite]
    candidatas, aprobadas, juzgadas = [], 0, []
    for item in items:
        try:
            r = correr(app, item, user_id)
        except Exception as exc:  # noqa: BLE001 - un timeout no debe perder lo aprendido
            print(f"[{item['id']}] ERROR: {exc}")
            continue
        juzgadas.append(item["id"])
        oraculo = juzgar(item["peticion"], r["respuesta"], item["referencia"])
        candidatas += r["reglas_nuevas"]
        if oraculo.paso:
            aprobadas += 1
        else:
            reflexion = invocar_estructurado(
                Reflexion,
                prompt_reflexion(item["peticion"], r["respuesta"], [oraculo.motivo], []),
                EVAL_MODEL,
                Reflexion(diagnostico=oraculo.motivo, plan=""),
            )
            if reflexion.regla_general:
                candidatas.append(reflexion.regla_general)
        print(f"[{item['id']}] oráculo={'PASS' if oraculo.paso else 'FAIL'} ({oraculo.puntaje:.2f}) "
              f"reglas candidatas acumuladas={len(candidatas)}")
    reglas = consolidar_reglas(manual_reglas.cargar(AGENTE) + candidatas)
    if not reglas:
        print("Sin reglas candidatas: el manual vigente no se modifica.")
        return
    entrada = manual_reglas.guardar(AGENTE, reglas, preguntas=juzgadas,
                                    candidatas=candidatas, oraculo_pass=f"{aprobadas}/{len(juzgadas)}")
    print(f"Manual v{entrada['version']} ({entrada['modelo']}): {len(reglas)} reglas")
    for k, regla in enumerate(reglas, 1):
        print(f"{k}. {regla}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--email", default="demo@instituto.local")
    p.add_argument("--limite", type=int)
    a = p.parse_args()
    entrenar(a.email, a.limite)
