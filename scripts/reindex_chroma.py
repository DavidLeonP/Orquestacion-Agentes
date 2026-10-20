"""Copia a Chroma los vectores de `chunk_embeddings` (sin volver a embeber).

Opcional: el retriever ya sincroniza solo en su primera búsqueda. Sirve para
migrar todo de una vez al activar VECTOR_BACKEND=chroma o al cambiar de modelo.

Uso:
  python scripts/reindex_chroma.py [--forzar]   # --forzar reescribe también los presentes
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db.models import Chunk
from src.db.session import SessionLocal
from src.rag import kb_vectores


def main(forzar: bool) -> None:
    db = SessionLocal()
    try:
        total = 0
        for user_id, indice in db.query(Chunk.user_id, Chunk.indice).distinct():
            uids = [u for (u,) in db.query(Chunk.chunk_uid).filter(
                Chunk.user_id == user_id, Chunk.indice == indice)]
            n = kb_vectores.sincronizar(db, user_id, indice, uids, forzar=forzar)
            total += n
            print(f"user={user_id} indice={indice}: {n} vectores copiados de {len(uids)} chunks")
        print(f"Total: {total}")
    finally:
        db.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--forzar", action="store_true")
    main(p.parse_args().forzar)
