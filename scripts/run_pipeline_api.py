#!/usr/bin/env python3
"""Ejecuta el pipeline completo contra la API HTTP y guarda resultados en JSON.

Uso:
  python scripts/run_pipeline_api.py
  BASE_URL=http://localhost:8000 python scripts/run_pipeline_api.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

BASE_URL = os.getenv("BASE_URL") or os.getenv("API_BASE_URL") or "http://127.0.0.1:8000"
BASE_URL = BASE_URL.rstrip("/")
OUT_JSON = ROOT / "docs" / "_pipeline_run_raw.json"
TIMEOUT = 300


def request(method: str, path: str, body: dict | None = None) -> dict:
    url = f"{BASE_URL}{path}"
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode("utf-8")
            payload = json.loads(raw) if raw else {}
            return {
                "ok": True,
                "status_code": resp.status,
                "elapsed_s": round(time.perf_counter() - started, 2),
                "response": payload,
            }
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"raw": raw}
        return {
            "ok": False,
            "status_code": exc.code,
            "elapsed_s": round(time.perf_counter() - started, 2),
            "response": payload,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "status_code": None,
            "elapsed_s": round(time.perf_counter() - started, 2),
            "response": {"error": str(exc)},
        }


def main() -> int:
    report: dict = {
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "base_url": BASE_URL,
        "steps": {},
    }

    print(f"Base URL: {BASE_URL}")
    report["steps"]["health"] = request("GET", "/api/v1/health")
    print("health:", report["steps"]["health"]["status_code"], report["steps"]["health"]["response"])

    report["steps"]["ingestar"] = request("POST", "/api/v1/ingestar")
    print("ingestar:", report["steps"]["ingestar"]["status_code"], report["steps"]["ingestar"]["response"])

    report["steps"]["chat_alumno"] = request(
        "POST",
        "/api/v1/chat",
        {
            "peticion": "No entiendo la diferencia entre circuito en serie y en paralelo, explícamelo con ejemplos del instituto.",
            "rol": "alumno",
            "alumno_id": "alumno-pipeline-001",
        },
    )
    print(
        "chat_alumno:",
        report["steps"]["chat_alumno"]["status_code"],
        report["steps"]["chat_alumno"]["response"].get("status")
        or report["steps"]["chat_alumno"]["response"],
    )

    report["steps"]["chat_docente_examen"] = request(
        "POST",
        "/api/v1/chat",
        {
            "peticion": (
                "Genera un examen de 6 preguntas sobre electricidad y circuitos "
                "para Tecnología de 3º ESO, dificultad media, 55 minutos."
            ),
            "rol": "docente",
        },
    )
    exam = report["steps"]["chat_docente_examen"]
    print(
        "chat_docente_examen:",
        exam["status_code"],
        exam["response"].get("status") or exam["response"],
    )

    thread_id = (exam.get("response") or {}).get("thread_id")
    if exam.get("ok") and exam["response"].get("status") == "awaiting_approval" and thread_id:
        report["steps"]["approve"] = request(
            "POST",
            "/api/v1/approve",
            {"thread_id": thread_id, "decision": "si"},
        )
        print(
            "approve:",
            report["steps"]["approve"]["status_code"],
            report["steps"]["approve"]["response"].get("status")
            or report["steps"]["approve"]["response"],
        )
    else:
        report["steps"]["approve"] = {
            "ok": False,
            "status_code": None,
            "elapsed_s": 0,
            "response": {"skipped": True, "reason": "No había awaiting_approval"},
        }

    report["steps"]["chat_docente_curriculum"] = request(
        "POST",
        "/api/v1/chat",
        {
            "peticion": (
                "Estructura la unidad de electricidad de Tecnología de 3º ESO "
                "en sesiones, alineada con la programación del centro."
            ),
            "rol": "docente",
        },
    )
    print(
        "chat_docente_curriculum:",
        report["steps"]["chat_docente_curriculum"]["status_code"],
        report["steps"]["chat_docente_curriculum"]["response"].get("status")
        or report["steps"]["chat_docente_curriculum"]["response"],
    )

    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Raw JSON: {OUT_JSON}")

    critical = ["health", "ingestar", "chat_alumno", "chat_docente_examen"]
    failed = [name for name in critical if not report["steps"][name].get("ok")]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
