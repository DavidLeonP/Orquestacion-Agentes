#!/usr/bin/env python3
"""Siembra la aclaración canónica «año pasado» para todos los docentes.

Útil tras deploy (local/prod) para que la UI muestre el mismo aprendizaje
que en las pruebas del pipeline.

  python scripts/seed_clarificaciones_sql_docentes.py
  python scripts/seed_clarificaciones_sql_docentes.py --also-tenant pipeline-sintetica
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)

from src.db.models import User  # noqa: E402
from src.db.session import SessionLocal  # noqa: E402
from src.memory.clarificaciones_sql import seed_anio_pasado  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--also-tenant",
        action="append",
        default=[],
        help="Tenant extra (p. ej. pipeline-sintetica). Repetible.",
    )
    args = parser.parse_args()

    tenants: list[str] = []
    db = SessionLocal()
    try:
        docentes = db.query(User).filter(User.rol == "docente").all()
        tenants.extend(str(u.id) for u in docentes)
        print(f"docentes={len(docentes)}", flush=True)
    finally:
        db.close()

    for t in args.also_tenant:
        if t not in tenants:
            tenants.append(t)

    ok = 0
    for tenant in tenants:
        vid = seed_anio_pasado(tenant)
        print(f"  tenant={tenant!r} id={vid}", flush=True)
        if vid:
            ok += 1
    print(f"OK={ok}/{len(tenants)}", flush=True)
    return 0 if ok == len(tenants) and tenants else (0 if not tenants else 1)


if __name__ == "__main__":
    raise SystemExit(main())
