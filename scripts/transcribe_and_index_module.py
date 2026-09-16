#!/usr/bin/env python3
"""Transcribe un vídeo de módulo + indexa PDF/vídeo en MySQL (usuario demo).

Uso:
  python scripts/transcribe_and_index_module.py
  python scripts/transcribe_and_index_module.py --video path/al.mp4 --max-seconds 180
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)


def _force_openai_cloud() -> None:
    for k in ("LLM_BASE_URL", "EMBEDDING_BASE_URL", "EMBEDDING_PROVIDER", "LLM_PROVIDER"):
        os.environ.pop(k, None)
    os.environ["LLM_PROFILE"] = "cloud_openai"
    os.environ.setdefault("LLM_MODEL", "gpt-4o-mini")
    os.environ.setdefault("EMBEDDING_MODEL", "text-embedding-3-small")
    os.environ.setdefault("WHISPER_PROVIDER", "openai")
    os.environ.setdefault("WHISPER_MODEL", "whisper-1")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--modulo",
        default="contabilidadFinaciera",
        help="Carpeta de módulo bajo la raíz del repo",
    )
    parser.add_argument(
        "--video",
        default=None,
        help="Ruta al MP4 (default: GMT20251122… del módulo)",
    )
    parser.add_argument("--email", default="demo@instituto.local")
    parser.add_argument("--indice", default="apuntes")
    parser.add_argument(
        "--max-seconds",
        type=float,
        default=None,
        help="Limitar ASR (omitir = vídeo completo)",
    )
    parser.add_argument("--skip-pdf", action="store_true")
    parser.add_argument("--skip-index", action="store_true")
    args = parser.parse_args()

    _force_openai_cloud()

    from src.llm import (
        active_embedding_model,
        get_selection,
        invalidate_registry_cache,
    )

    invalidate_registry_cache()
    print("profile", get_selection().describe(), flush=True)

    from src.config import DIR_STORAGE, RAIZ
    from src.db.models import Document, User
    from src.db.session import SessionLocal
    from src.ingestion.extractors.pdf import extraer_pdf
    from src.ingestion.extractors.video import extraer_video
    from src.ingestion.module_media import _frontmatter
    from src.ingestion.mysql_pipeline import indexar_documento

    modulo = RAIZ / args.modulo
    out = DIR_STORAGE / "extracted" / modulo.name
    out.mkdir(parents=True, exist_ok=True)
    metrics: dict = {"started_at": time.time(), "steps": {}}
    paths_to_index: list[tuple[Path, dict]] = []

    if not args.skip_pdf:
        pdf = next(modulo.rglob("*.pdf"), None)
        if pdf is None:
            raise SystemExit(f"No hay PDF en {modulo}")
        t0 = time.time()
        pdf_res = extraer_pdf(pdf, dry_run=False)
        pdf_body = _frontmatter(
            "Finanzas Estratégicas",
            pdf.stem,
            "pdf",
            {
                "modulo": modulo.name,
                "indice": args.indice,
                "fuente_original": pdf.name,
                "pages": pdf_res.metadatos.get("pages"),
            },
        ) + pdf_res.content_text
        pdf_path = out / "Guia_didactica.txt"
        pdf_path.write_text(pdf_body, encoding="utf-8")
        metrics["steps"]["pdf_extract"] = {
            "chars": len(pdf_res.content_text),
            "sec": round(time.time() - t0, 2),
        }
        paths_to_index.append(
            (pdf_path, {"media_tipo": "pdf", "modulo": modulo.name})
        )
        print("PDF ready", metrics["steps"]["pdf_extract"], flush=True)

    if args.video:
        video = Path(args.video)
        if not video.is_absolute():
            video = RAIZ / video
    else:
        video = (
            modulo
            / "Finanzas"
            / "GMT20251122-001420_Recording_1686x768.mp4"
        )
    if not video.exists():
        raise SystemExit(f"Vídeo no encontrado: {video}")

    print(
        f"ASR start {video.name} max_seconds={args.max_seconds}",
        flush=True,
    )
    t1 = time.time()
    vid_res = extraer_video(
        video,
        dry_run=False,
        language="es",
        max_seconds=args.max_seconds,
    )
    vid_body = _frontmatter(
        "Finanzas Estratégicas",
        video.stem,
        "video",
        {
            "modulo": modulo.name,
            "indice": args.indice,
            "fuente_original": video.name,
            "duration_sec": vid_res.estimated_duration_sec,
            "asr_full": args.max_seconds is None,
            "max_seconds": args.max_seconds,
        },
    ) + vid_res.content_text
    vid_path = out / f"{video.stem}.txt"
    vid_path.write_text(vid_body, encoding="utf-8")
    (out / f"{video.stem}.meta.json").write_text(
        json.dumps(vid_res.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    metrics["steps"]["video_asr"] = {
        "file": video.name,
        "chars": len(vid_res.content_text),
        "duration_sec": vid_res.estimated_duration_sec,
        "sec": round(time.time() - t1, 2),
        "preview": vid_res.content_text[:500],
    }
    paths_to_index.append(
        (
            vid_path,
            {
                "media_tipo": "video",
                "modulo": modulo.name,
                "asr_full": args.max_seconds is None,
            },
        )
    )
    print(
        "ASR done",
        {k: v for k, v in metrics["steps"]["video_asr"].items() if k != "preview"},
        flush=True,
    )

    if not args.skip_index:
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.email == args.email).first()
            if user is None:
                raise SystemExit(f"Usuario {args.email} no existe")
            indexed = []
            for path, meta in paths_to_index:
                text = path.read_text(encoding="utf-8")
                doc = (
                    db.query(Document)
                    .filter(
                        Document.user_id == user.id,
                        Document.indice == args.indice,
                        Document.filename == path.name,
                    )
                    .first()
                )
                if doc is None:
                    doc = Document(
                        user_id=user.id,
                        indice=args.indice,
                        filename=path.name,
                        content_text=text,
                        content_type="text/plain",
                        status="pending",
                        metadatos={"fuente": path.name, **meta},
                    )
                    db.add(doc)
                else:
                    doc.content_text = text
                    doc.status = "pending"
                    doc.error_msg = None
                    doc.metadatos = {"fuente": path.name, **meta}
                db.commit()
                db.refresh(doc)
                t2 = time.time()
                n = indexar_documento(db, doc)
                indexed.append(
                    {
                        "document_id": doc.id,
                        "filename": doc.filename,
                        "chunks": n,
                        "status": doc.status,
                        "embed_model": active_embedding_model(),
                        "embed_sec": round(time.time() - t2, 2),
                        "chars": len(text),
                    }
                )
                print("INDEXED", indexed[-1], flush=True)
            metrics["steps"]["index"] = indexed
        finally:
            db.close()

    metrics["elapsed_sec"] = round(time.time() - metrics["started_at"], 2)
    metrics["ok"] = True
    out_json = DIR_STORAGE / "metrics" / "openai-full-video-index.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print("DONE", out_json, "elapsed", metrics["elapsed_sec"], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
