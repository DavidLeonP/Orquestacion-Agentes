#!/usr/bin/env python3
"""Legacy: antes creaba un SQLite mínimo (5 alumnos ESO).

Ahora delega en la BD sintética universitaria (500 estudiantes):

  python scripts/generar_sintetica_academica.py
  python scripts/migrar_sintetica_academica.py

Ver data/sintetica_academica/README.md
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    print(
        "seed_negocio_demo.py delega en la sintética académica "
        "(data/sintetica_academica/).",
        flush=True,
    )
    gen = subprocess.call([sys.executable, str(ROOT / "scripts" / "generar_sintetica_academica.py")])
    if gen != 0:
        return gen
    return subprocess.call([sys.executable, str(ROOT / "scripts" / "migrar_sintetica_academica.py")])


if __name__ == "__main__":
    raise SystemExit(main())
