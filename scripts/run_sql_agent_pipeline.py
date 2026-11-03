#!/usr/bin/env python3
"""Pipeline de verificación del SQL Agent contra la BD sintética académica.

1) Asegura JSON + SQLite (genera/migra si faltan)
2) Carga el grafo de conocimiento
3) Ejecuta preguntas de control (top-10, paralelo, afinidad, fuera de esquema)
4) Opcional: --write-doc → docs/resultados-sql-agent-pipeline.md

Uso:
  python scripts/run_sql_agent_pipeline.py
  python scripts/run_sql_agent_pipeline.py --write-doc
  python scripts/run_sql_agent_pipeline.py --skip-llm   # solo BD + KG
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)

DIR = ROOT / "data" / "sintetica_academica"
JSON_PATH = DIR / "estudiantes_sinteticos.json"
DB_PATH = ROOT / "data" / "negocio_academico.db"
DOC_PATH = ROOT / "docs" / "resultados-sql-agent-pipeline.md"


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str = "", **data: Any) -> None:
        self.checks.append(Check(name, ok, detail, data))
        print(f"  [{'OK' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""), flush=True)

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(c.ok for c in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "passed": self.passed,
            "checks": [asdict(c) for c in self.checks],
        }


def _load_script(nombre: str, path: Path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(nombre, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se pudo cargar {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ensure_db(report: Report) -> str:
    gen = _load_script("generar_sintetica", ROOT / "scripts" / "generar_sintetica_academica.py")
    mig = _load_script("migrar_sintetica", ROOT / "scripts" / "migrar_sintetica_academica.py")

    if not JSON_PATH.exists():
        data = gen.generar(500, 42)
        JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
        JSON_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        report.add("generar_json", True, f"n={len(data['estudiantes'])}")
    else:
        report.add("generar_json", True, f"ya existe {JSON_PATH.name}")

    schema = DIR / "schema.sqlite.sql"
    conteos = mig.migrar(JSON_PATH, DB_PATH, schema)
    ok = conteos.get("estudiantes", 0) == 500 and conteos.get("calificaciones", 0) > 0
    report.add(
        "migrar_sqlite",
        ok,
        f"estudiantes={conteos.get('estudiantes')} calificaciones={conteos.get('calificaciones')}",
        **conteos,
    )
    return mig.uri_sqlite(DB_PATH)


def _check_kg(report: Report) -> None:
    from src.sql_agent.knowledge_graph import (
        cargar_knowledge_graph,
        invalidar_cache_kg,
        render_contexto_esquema,
    )

    invalidar_cache_kg()
    kg = cargar_knowledge_graph()
    ok = kg is not None and len(kg.get("entidades") or []) >= 10
    report.add(
        "knowledge_graph",
        ok,
        f"entidades={len((kg or {}).get('entidades') or [])} relaciones={len((kg or {}).get('relaciones') or [])}",
    )
    ctx = render_contexto_esquema(kg)
    report.add(
        "kg_contexto_prompt",
        "promedios_periodo" in ctx and "Reglas anti-alucinación" in ctx,
        f"len={len(ctx)}",
    )
    report.add(
        "kg_regla_anio_pasado",
        "anio_ingreso" in ctx and "MAX(anio_fin)" in ctx,
        "regla temporal en KG",
    )


def _seed_clarificacion(report: Report) -> None:
    """Siembra en Chroma el caso canónico «año pasado» para el tenant del pipeline."""
    try:
        from src.memory.clarificaciones_sql import recordar, seed_anio_pasado

        vid = seed_anio_pasado("pipeline-sintetica")
        hits = recordar(
            "pipeline-sintetica",
            "estudiantes que se matricularon el año pasado",
            k=3,
        )
        ok = bool(vid) and any("anio_ingreso" in h.lower() for h in hits)
        report.add(
            "seed_clarificacion_chroma",
            ok,
            f"id={vid} hits={len(hits)}",
        )
    except Exception as exc:  # noqa: BLE001
        report.add("seed_clarificacion_chroma", False, str(exc)[:300])


def _check_sql_directo(report: Report) -> None:
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT e.codigo, e.nombre, p.promedio
            FROM promedios_periodo p
            JOIN estudiantes e ON e.id = p.estudiante_id
            JOIN periodos pe ON pe.id = p.periodo_id
            WHERE pe.codigo = '2023-2024'
            ORDER BY p.promedio DESC
            LIMIT 10
            """
        )
        top = cur.fetchall()
        report.add("sql_top10_2023", len(top) == 10, f"primero={top[0] if top else None}")

        cur.execute(
            """
            SELECT par.codigo, ROUND(AVG(c.nota), 3)
            FROM calificaciones c
            JOIN matriculas m ON m.id = c.matricula_id
            JOIN ofertas o ON o.id = m.oferta_id
            JOIN paralelos par ON par.id = o.paralelo_id
            JOIN materias mat ON mat.id = o.materia_id
            WHERE mat.codigo = 'MAT101'
            GROUP BY par.codigo
            ORDER BY par.codigo
            """
        )
        por_par = cur.fetchall()
        report.add("sql_promedio_paralelo_calculo", len(por_par) == 3, str(por_par))
    finally:
        conn.close()


def _run_agent_cases(report: Report, uri: str, skip_llm: bool) -> None:
    if skip_llm:
        report.add("sql_agent_llm", True, "omitido (--skip-llm)")
        return

    from langchain_community.utilities import SQLDatabase
    from langgraph.checkpoint.memory import MemorySaver

    from src.sql_agent.graph import construir_grafo

    db = SQLDatabase.from_uri(uri)
    app = construir_grafo(tenant="pipeline-sintetica", db=db, checkpointer=MemorySaver())

    casos = [
        {
            "name": "agent_top10",
            "pregunta": (
                "¿Cuáles son los 10 estudiantes con mejor promedio en el periodo 2023-2024? "
                "Lista codigo, nombre y promedio."
            ),
            "must_any": ("promedio", "est-", "2023", "top", "mejor"),
            "forbid": ("invent", "no tengo acceso"),
            "sql_forbid": (),
        },
        {
            "name": "agent_paralelo",
            "pregunta": "¿Cuál es el promedio de notas del paralelo B en la materia Cálculo I (MAT101)?",
            "must_any": ("paralelo", "b", "promedio", "cálculo", "calculo", "mat101"),
            "forbid": (),
            "sql_forbid": (),
        },
        {
            "name": "agent_anio_pasado",
            "pregunta": (
                "¿Cuáles son los estudiantes que se matricularon el año pasado? "
                "Lista codigo, nombre, carrera y periodo. Si hay muchos, total + primeros 20."
            ),
            # Con memoria Chroma sembrada debe usar el último periodo, no cohorte 2022.
            "must_any": ("2024-2025", "2024", "periodo", "matricul", "estudiante"),
            "forbid": (),
            "sql_forbid": ("anio_ingreso",),
        },
        {
            "name": "agent_fuera_esquema",
            "pregunta": "¿Cuántos buses eléctricos hay en el campus universitario?",
            "must_any": (
                "no",
                "no hay",
                "no consta",
                "no existe",
                "esquema",
                "tablas",
                "no puedo",
                "no dispon",
            ),
            "forbid": (),
            "sql_forbid": (),
        },
    ]

    for caso in casos:
        t0 = time.time()
        try:
            estado = app.invoke(
                {
                    "messages": [("user", caso["pregunta"])],
                    "peticion": caso["pregunta"],
                    "lecciones": [],
                    "clarificaciones": [],
                    "intentos_validacion": 0,
                },
                {
                    "configurable": {"thread_id": f"pipe-{caso['name']}-{int(time.time())}"},
                    "recursion_limit": 60,
                },
            )
            mensajes = estado.get("messages") or []
            texto = ""
            for m in reversed(mensajes):
                tcs = getattr(m, "tool_calls", None) or []
                for tc in tcs:
                    if tc.get("name") == "SubmitFinalAnswer":
                        texto = (tc.get("args") or {}).get("final_answer") or ""
                        break
                if texto:
                    break
                content = getattr(m, "content", "") or ""
                if isinstance(content, str) and content.strip() and not tcs:
                    texto = content
                    break
            sql_final = (estado.get("sql_final") or "").lower()
            low = texto.lower()
            ok_must = any(x in low for x in caso["must_any"])
            ok_forbid = not any(x in low for x in caso["forbid"])
            ok_sql = not any(x in sql_final for x in caso.get("sql_forbid") or ())
            report.add(
                caso["name"],
                bool(texto) and ok_must and ok_forbid and ok_sql,
                f"t={round(time.time() - t0, 2)}s sql_ok={ok_sql} preview={texto[:180]!r}",
                respuesta=texto[:800],
                sql_final=sql_final[:500],
                lecciones=estado.get("lecciones") or [],
            )
        except Exception as exc:  # noqa: BLE001
            # GraphInterrupt = pidió aclaración humana (válido si no había memoria).
            nombre = type(exc).__name__
            report.add(caso["name"], False, f"{nombre}: {str(exc)[:280]}")


def _write_doc(report: Report, uri: str) -> None:
    lines = [
        "# Resultados — pipeline SQL Agent (BD sintética académica)",
        "",
        f"**Generado (UTC):** {report.to_dict()['generated_at']}",
        f"**Resultado global:** {'PASS' if report.passed else 'FAIL'}",
        f"**AGENT_DB_URI:** `{uri}`",
        f"**Knowledge graph:** `data/sintetica_academica/knowledge_graph.json`",
        "",
        "## Checks",
        "",
        "| Check | OK | Detalle |",
        "|---|---|---|",
    ]
    for c in report.checks:
        det = (c.detail or "").replace("|", "/").replace("\n", " ")[:200]
        lines.append(f"| `{c.name}` | {'✅' if c.ok else '❌'} | {det} |")
    lines += [
        "",
        "## Cómo reproducir",
        "",
        "```bash",
        "python scripts/generar_sintetica_academica.py",
        "python scripts/migrar_sintetica_academica.py",
        "python scripts/run_sql_agent_pipeline.py --write-doc",
        "```",
        "",
        "Parametrización: `AGENT_DB_URI`, `SQL_AGENT_KG_PATH` (ver `.env.example`).",
        "",
    ]
    DOC_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"DOC: {DOC_PATH}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-llm", action="store_true")
    parser.add_argument("--write-doc", action="store_true")
    args = parser.parse_args()

    report = Report()
    print("== Pipeline SQL Agent / sintética académica ==", flush=True)
    uri = _ensure_db(report)
    _check_kg(report)
    _seed_clarificacion(report)
    _check_sql_directo(report)
    _run_agent_cases(report, uri, args.skip_llm)

    metrics = ROOT / "storage" / "metrics" / "sql-agent-pipeline.json"
    metrics.parent.mkdir(parents=True, exist_ok=True)
    metrics.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"JSON: {metrics}", flush=True)
    print(f"PASS={report.passed}", flush=True)
    print(f"Sugerencia .env → AGENT_DB_URI={uri}", flush=True)

    if args.write_doc:
        _write_doc(report, uri)
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
