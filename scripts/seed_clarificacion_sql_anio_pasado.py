#!/usr/bin/env python3
"""Siembra en Chroma la aclaración canónica «año pasado» ≠ anio_ingreso.

Uso:
  python scripts/seed_clarificacion_sql_anio_pasado.py
  python scripts/seed_clarificacion_sql_anio_pasado.py --tenant 1
  python scripts/seed_clarificacion_sql_anio_pasado.py --tenant pipeline-sintetica
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)

from src.memory.clarificaciones_sql import seed_anio_pasado  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tenant",
        default="pipeline-sintetica",
        help="Tenant / user_id del SQL Agent (default: pipeline-sintetica)",
    )
    args = parser.parse_args()
    vid = seed_anio_pasado(args.tenant)
    if not vid:
        print("FAIL: no se pudo archivar en Chroma", flush=True)
        return 1
    print(f"OK tenant={args.tenant!r} chroma_id={vid}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
