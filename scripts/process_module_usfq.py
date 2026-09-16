#!/usr/bin/env python3
"""Procesa un módulo de conocimiento con perfil universidad (vLLM USFQ).

Pasos:
  1) Extrae PDF (y vídeo si --with-video y hay ffmpeg/ASR)
  2) Crea Documents pending en MySQL para el usuario demo (o --email)
  3) Indexa embeddings vía EMBEDDING_BASE_URL (bge-m3)

Ejemplo:
  LLM_PROFILE=vllm_usfq python scripts/process_module_usfq.py contabilidadFinaciera
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")


def _wait_embeddings(timeout_sec: float = 30.0) -> None:
    import httpx
    import os

    base = (os.getenv("EMBEDDING_BASE_URL") or "http://172.28.230.10:12556/v1").rstrip(
        "/"
    )
    key = os.getenv("OPENAI_COMPAT_API_KEY", "local")
    deadline = time.time() + timeout_sec
    last_err = None
    while time.time() < deadline:
        try:
            r = httpx.get(
                f"{base}/models",
                headers={"Authorization": f"Bearer {key}"},
                timeout=5.0,
            )
            r.raise_for_status()
            print(f"Embeddings OK en {base}: {r.json()}")
            return
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(2)
    raise RuntimeError(
        f"Servicio de embeddings no disponible en {base} ({last_err}). "
        "Confirma que :12556 esté arriba o pasa --embed-url."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("modulo", nargs="?", default="contabilidadFinaciera")
    parser.add_argument("--email", default="demo@instituto.local")
    parser.add_argument("--indice", default="apuntes")
    parser.add_argument(
        "--with-video",
        action="store_true",
        help="También transcribe MP4 (requiere ffmpeg + WHISPER_*)",
    )
    parser.add_argument("--embed-url", default=None, help="Override EMBEDDING_BASE_URL")
    parser.add_argument(
        "--skip-embed-check",
        action="store_true",
        help="No verificar embeddings antes de indexar",
    )
    parser.add_argument(
        "--extract-only",
        action="store_true",
        help="Solo extrae a storage/extracted (sin MySQL ni embeddings)",
    )
    args = parser.parse_args()

    import os

    os.environ.setdefault("LLM_PROFILE", "vllm_usfq")
    if args.embed_url:
        os.environ["EMBEDDING_BASE_URL"] = args.embed_url.rstrip("/")

    from src.llm import invalidate_registry_cache
    from src.ingestion.module_media import (
        commit_extracted_a_mysql,
        preparar_modulo,
        resolver_ruta_modulo,
    )

    invalidate_registry_cache()
    ruta = resolver_ruta_modulo(args.modulo)
    print(f"Módulo: {ruta}")
    print(f"Perfil: {os.getenv('LLM_PROFILE')} embed={os.getenv('EMBEDDING_BASE_URL')}")

    # Extracción: por defecto PDF+text; vídeo solo con flag (caro / largo)
    if args.with_video:
        result = preparar_modulo(ruta, dry_run=False, indice=args.indice)
    else:
        # Extrae solo PDF/texto sin tocar MP4
        from src.config import DIR_STORAGE
        from src.ingestion.extractors.pdf import extraer_pdf
        from src.ingestion.module_media import _frontmatter
        import json as _json

        out = DIR_STORAGE / "extracted" / ruta.name
        out.mkdir(parents=True, exist_ok=True)
        extracciones = []
        for pdf in sorted(ruta.rglob("*.pdf")):
            res = extraer_pdf(pdf, dry_run=False)
            cab = _frontmatter(
                "Finanzas Estratégicas",
                pdf.stem,
                "pdf",
                {
                    "modulo": ruta.name,
                    "indice": args.indice,
                    "fuente_original": pdf.name,
                    "pages": res.metadatos.get("pages"),
                },
            )
            body = cab + res.content_text
            dest = out / "Guia_didactica.txt"
            dest.write_text(body, encoding="utf-8")
            meta = out / "Guia_didactica.meta.json"
            meta.write_text(
                _json.dumps(res.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            extracciones.append({"filename": dest.name, "chars": len(body)})
        for txt in sorted(ruta.rglob("*.txt")) + sorted(ruta.rglob("*.md")):
            body = txt.read_text(encoding="utf-8", errors="replace")
            (out / txt.name).write_text(body, encoding="utf-8")
            extracciones.append({"filename": txt.name, "chars": len(body)})
        result = {"out_dir": str(out), "extracciones": extracciones, "dry_run": False}

    print(json.dumps({"out_dir": result.get("out_dir"), "n": len(result.get("extracciones") or [])}, indent=2))

    if args.extract_only:
        print("extract-only: listo.")
        return 0

    if not args.skip_embed_check:
        _wait_embeddings(timeout_sec=20)

    from src.db.models import User
    from src.db.session import SessionLocal

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == args.email).first()
        if user is None:
            raise SystemExit(
                f"Usuario '{args.email}' no existe. Ejecuta scripts/seed_demo_kb.py o registra uno."
            )
        out_dir = Path(result["out_dir"])
        commit = commit_extracted_a_mysql(
            db,
            user_id=user.id,
            extracted_dir=out_dir,
            indice=args.indice,
            indexar=True,
        )
        print(json.dumps(commit, ensure_ascii=False, indent=2))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
