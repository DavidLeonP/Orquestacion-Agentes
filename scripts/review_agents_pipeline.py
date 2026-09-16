#!/usr/bin/env python3
"""Pipeline de revisión: implementación media + interacción de agentes.

Comprueba:
  1) Perfil LLM / embeddings
  2) Extractores PDF/vídeo presentes
  3) Documentos indexados del módulo (MySQL)
  4) Retriever híbrido sobre apuntes
  5) Orquestador: alumno→tutor y docente→curriculum/exam (smoke)
  6) Informe Markdown en docs/ o storage/metrics/

Uso:
  python scripts/review_agents_pipeline.py
  python scripts/review_agents_pipeline.py --write-doc
  python scripts/review_agents_pipeline.py --skip-llm   # sin llamadas al orquestador
"""

from __future__ import annotations

import argparse
import json
import os
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


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReviewReport:
    checks: list[Check] = field(default_factory=list)
    agent_traces: list[dict[str, Any]] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str = "", **data: Any) -> None:
        self.checks.append(Check(name, ok, detail, data))
        mark = "OK" if ok else "FAIL"
        print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""), flush=True)

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(c.ok for c in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "passed": self.passed,
            "checks": [c.to_dict() for c in self.checks],
            "agent_traces": self.agent_traces,
        }


def _check_profile(report: ReviewReport) -> None:
    from src.llm import get_selection, invalidate_registry_cache

    invalidate_registry_cache()
    sel = get_selection()
    report.add(
        "model_registry",
        True,
        f"profile={sel.profile} llm={sel.llm_model} emb={sel.embedding_model}",
        **sel.describe(),
    )


def _check_extractors(report: ReviewReport) -> None:
    from src.ingestion.extractors import extraer_pdf, extraer_video
    from src.ingestion.extractors.video import _ffmpeg_bin
    from src.ingestion import module_media, cost_estimate

    try:
        ff = _ffmpeg_bin()
        report.add("ffmpeg", True, ff)
    except Exception as exc:  # noqa: BLE001
        report.add("ffmpeg", False, str(exc))

    report.add(
        "extractors_modules",
        True,
        "pdf/video/module_media/cost_estimate importables",
        has_pdf=callable(extraer_pdf),
        has_video=callable(extraer_video),
        has_module_media=hasattr(module_media, "estimar_coste_modulo"),
        has_cost=hasattr(cost_estimate, "comparar_perfiles"),
    )


def _check_indexed_module(report: ReviewReport, email: str, modulo: str) -> int | None:
    from src.db.models import Chunk, ChunkEmbedding, Document, User
    from src.db.session import SessionLocal

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if user is None:
            report.add("demo_user", False, f"{email} no existe")
            return None
        report.add("demo_user", True, f"id={user.id} rol={user.rol}")

        docs = (
            db.query(Document)
            .filter(Document.user_id == user.id, Document.indice == "apuntes")
            .all()
        )
        modulo_docs = [
            d
            for d in docs
            if modulo.lower() in (d.filename or "").lower()
            or (d.metadatos or {}).get("modulo") == modulo
            or "Guia_didactica" in (d.filename or "")
            or "GMT2025" in (d.filename or "")
        ]
        detail_rows = []
        for d in modulo_docs:
            n_chunks = db.query(Chunk).filter(Chunk.document_id == d.id).count()
            n_emb = (
                db.query(ChunkEmbedding)
                .join(Chunk, Chunk.id == ChunkEmbedding.chunk_id)
                .filter(Chunk.document_id == d.id)
                .count()
            )
            detail_rows.append(
                {
                    "id": d.id,
                    "filename": d.filename,
                    "status": d.status,
                    "chunks": n_chunks,
                    "embeddings": n_emb,
                    "chars": len(d.content_text or ""),
                }
            )
        ok = any(r["status"] == "indexed" and r["chunks"] > 0 for r in detail_rows)
        report.add(
            "modulo_indexed",
            ok,
            f"{len(detail_rows)} docs del módulo; indexed={ok}",
            documents=detail_rows,
        )
        return user.id
    finally:
        db.close()


def _check_retriever(report: ReviewReport, user_id: int) -> None:
    from src.rag.context import set_rag_user_id
    from src.rag.tools import buscar_apuntes

    set_rag_user_id(user_id)
    t0 = time.time()
    hits = buscar_apuntes.invoke(
        {"consulta": "costos de operación y proyección financiera"}
    )
    elapsed = round(time.time() - t0, 2)
    text = hits if isinstance(hits, str) else str(hits)
    ok = bool(text.strip()) and "No hay" not in text[:80]
    report.add(
        "retriever_apuntes",
        ok,
        f"len={len(text)} t={elapsed}s",
        preview=text[:500],
    )


def _run_agent_interaction(
    report: ReviewReport,
    user_id: int,
    *,
    skip_llm: bool,
) -> None:
    if skip_llm:
        report.add("agent_interactions", True, "omitido (--skip-llm)")
        return

    from src.observability.trazas import configurar_observabilidad
    from src.orchestrator.graph import construir_grafo
    from src.rag.context import set_rag_user_id
    from src.memory import mysql_store as mem

    configurar_observabilidad()
    set_rag_user_id(user_id)
    mem.set_memory_user_id(user_id)
    app = construir_grafo()

    scenarios = [
        {
            "name": "alumno_tutor_finanzas",
            "rol": "alumno",
            "peticion": (
                "Con los apuntes de Finanzas Estratégicas, explícame qué es un "
                "costo de operación frente a un costo de producción y dame un ejemplo."
            ),
            "expect_agent": "tutor",
        },
        {
            "name": "docente_curriculum_finanzas",
            "rol": "docente",
            "peticion": (
                "Estructura en 4 sesiones una unidad introductoria de Finanzas "
                "Estratégicas usando la guía didáctica y la clase grabada indexada."
            ),
            "expect_agent": "curriculum",
        },
    ]

    for sc in scenarios:
        t0 = time.time()
        trace: dict[str, Any] = {
            "scenario": sc["name"],
            "rol": sc["rol"],
            "nodos": [],
            "agente_destino": None,
            "respuesta_preview": None,
            "error": None,
        }
        try:
            estado: dict[str, Any] = {}
            for chunk in app.stream(
                {
                    "peticion": sc["peticion"],
                    "rol_usuario": sc["rol"],
                    "alumno_id": "review-pipeline",
                },
                config={"configurable": {"thread_id": f"review-{sc['name']}-{int(time.time())}"}},
                stream_mode="updates",
            ):
                if "__interrupt__" in chunk:
                    trace["interrupt"] = True
                    break
                for nodo, upd in chunk.items():
                    if nodo.startswith("__"):
                        continue
                    trace["nodos"].append(nodo)
                    if isinstance(upd, dict):
                        if "agente_destino" in upd:
                            trace["agente_destino"] = upd["agente_destino"]
                        if "respuesta_final" in upd:
                            estado["respuesta_final"] = upd["respuesta_final"]
                        if "borrador" in upd and "respuesta_final" not in estado:
                            estado["borrador"] = upd["borrador"]
            final = estado.get("respuesta_final") or estado.get("borrador") or ""
            trace["respuesta_preview"] = final[:600]
            trace["elapsed_sec"] = round(time.time() - t0, 2)
            ok_route = (
                sc["rol"] != "alumno"
                or trace.get("agente_destino") == "tutor"
                or "tutor" in trace["nodos"]
            )
            ok_content = len(final) > 40
            report.add(
                f"agent:{sc['name']}",
                ok_route and ok_content,
                f"nodos={trace['nodos']} destino={trace.get('agente_destino')} t={trace['elapsed_sec']}s",
            )
        except Exception as exc:  # noqa: BLE001
            trace["error"] = str(exc)
            report.add(f"agent:{sc['name']}", False, str(exc)[:300])
        report.agent_traces.append(trace)


def _render_markdown(report: ReviewReport) -> str:
    lines = [
        "# Revisión de implementación e interacción de agentes",
        "",
        f"**Generado (UTC):** {report.to_dict()['generated_at']}",
        f"**Resultado global:** {'PASS' if report.passed else 'FAIL'}",
        "",
        "## 1. Checks",
        "",
        "| Check | OK | Detalle |",
        "|---|---|---|",
    ]
    for c in report.checks:
        det = (c.detail or "").replace("|", "/").replace("\n", " ")
        lines.append(f"| `{c.name}` | {'✅' if c.ok else '❌'} | {det} |")

    lines += [
        "",
        "## 2. Flujo de agentes (implementación)",
        "",
        "```mermaid",
        "flowchart TB",
        "  REQ[Peticion_API] --> ORQ[Orquestador_LangGraph]",
        "  ORQ --> R[router]",
        "  R -->|alumno_regla| T[Tutor_ReAct]",
        "  R -->|docente_LLM| C[Curriculum_ReAct]",
        "  R -->|docente_LLM| E[ExamGenerator_ReAct]",
        "  R -->|docente_LLM| Ru[Rubric_ReAct]",
        "  E --> V[validar_cruzada]",
        "  V -->|cambios| E",
        "  V -->|ok| H[aprobacion_docente_HITL]",
        "  T --> F[finalizar]",
        "  C --> F",
        "  Ru --> F",
        "  H --> END([respuesta_final])",
        "  F --> END",
        "  subgraph RAG[KB_por_usuario]",
        "    Tools[buscar_apuntes_examenes_rubricas_curriculo]",
        "    Hyb[BM25_plus_cosine_RRF]",
        "    MySQL[(chunks_embeddings)]",
        "  end",
        "  T --> Tools",
        "  C --> Tools",
        "  E --> Tools",
        "  Ru --> Tools",
        "  Tools --> Hyb --> MySQL",
        "```",
        "",
        "## 3. Pipeline de medios (PDF / vídeo)",
        "",
        "```mermaid",
        "sequenceDiagram",
        "  participant Mod as Modulo_profesor",
        "  participant Ext as extractors",
        "  participant ASR as Whisper_OpenAI",
        "  participant Pipe as mysql_pipeline",
        "  participant Emb as text_embedding_3_small",
        "  participant DB as MySQL",
        "  participant Ag as Agentes",
        "",
        "  Mod->>Ext: PDF / MP4",
        "  Ext->>Ext: pypdf extract_text",
        "  Ext->>ASR: audio segmentos Whisper",
        "  ASR-->>Ext: transcript",
        "  Ext->>Pipe: content_text pending",
        "  Pipe->>Emb: embed_documents",
        "  Pipe->>DB: chunks + embeddings",
        "  Ag->>DB: buscar_apuntes user_id",
        "```",
        "",
        "## 4. Trazas de esta corrida",
        "",
    ]
    for tr in report.agent_traces:
        lines.append(f"### `{tr.get('scenario')}`")
        lines.append(f"- Nodos: `{tr.get('nodos')}`")
        lines.append(f"- Destino: `{tr.get('agente_destino')}`")
        if tr.get("error"):
            lines.append(f"- Error: {tr['error']}")
        prev = (tr.get("respuesta_preview") or "").replace("\n", " ")
        if prev:
            lines.append(f"- Preview: {prev[:400]}")
        lines.append("")

    lines += [
        "## 5. Cómo reproducir",
        "",
        "```bash",
        "python scripts/transcribe_and_index_module.py",
        "python scripts/review_agents_pipeline.py --write-doc",
        "```",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", default="demo@instituto.local")
    parser.add_argument("--modulo", default="contabilidadFinaciera")
    parser.add_argument("--skip-llm", action="store_true")
    parser.add_argument("--write-doc", action="store_true")
    args = parser.parse_args()

    report = ReviewReport()
    print("== Revisión implementación / agentes ==", flush=True)
    _check_profile(report)
    _check_extractors(report)
    user_id = _check_indexed_module(report, args.email, args.modulo)
    if user_id is not None:
        _check_retriever(report, user_id)
        _run_agent_interaction(report, user_id, skip_llm=args.skip_llm)
    else:
        report.add("retriever_apuntes", False, "sin user_id")
        report.add("agent_interactions", False, "sin user_id")

    metrics_path = ROOT / "storage" / "metrics" / "review-agents-pipeline.json"
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"JSON: {metrics_path}", flush=True)
    print(f"PASS={report.passed}", flush=True)

    if args.write_doc:
        doc = ROOT / "docs" / "revision-implementacion-agentes.md"
        doc.write_text(_render_markdown(report), encoding="utf-8")
        print(f"DOC: {doc}", flush=True)

    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
