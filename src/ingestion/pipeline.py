"""Pipeline de ingesta: carga documentos, extrae metadatos, trocea e indexa.

Cada subcarpeta de data/ es un índice independiente (RAG multi-índice).
Los chunks se indexan en ChromaDB (búsqueda semántica) y se serializan a JSON
para construir el índice léxico BM25 en tiempo de consulta.
"""

import json
import re
from pathlib import Path

from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

from src.config import DIR_CHROMA, DIR_STORAGE, EMBEDDING_MODEL, INDICES

DIR_CHUNKS = DIR_STORAGE / "chunks"

CABECERA_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


def _leer_documento(ruta: Path) -> str:
    if ruta.suffix.lower() == ".pdf":
        return "\n".join(pagina.extract_text() or "" for pagina in PdfReader(ruta).pages)
    return ruta.read_text(encoding="utf-8")


def _extraer_metadatos(texto: str, ruta: Path) -> tuple[dict, str]:
    """Separa la cabecera YAML-like (clave: valor) del cuerpo del documento."""
    metadatos = {"fuente": ruta.name}
    match = CABECERA_RE.match(texto)
    if not match:
        return metadatos, texto
    for linea in match.group(1).splitlines():
        if ":" in linea:
            clave, valor = linea.split(":", 1)
            metadatos[clave.strip()] = valor.strip()
    return metadatos, texto[match.end():]


def ingestar(persistir: bool = True) -> dict[str, list[dict]]:
    """Procesa todos los índices y devuelve los chunks por índice."""
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
    embeddings = OpenAIEmbeddings(model=EMBEDDING_MODEL) if persistir else None
    resultado: dict[str, list[dict]] = {}

    for nombre_indice, carpeta in INDICES.items():
        chunks: list[dict] = []
        for ruta in sorted(carpeta.glob("*")):
            if ruta.suffix.lower() not in {".txt", ".md", ".pdf"}:
                continue
            metadatos, cuerpo = _extraer_metadatos(_leer_documento(ruta), ruta)
            for i, trozo in enumerate(splitter.split_text(cuerpo)):
                chunks.append({
                    "id": f"{ruta.stem}-{i}",
                    "texto": trozo,
                    "metadatos": metadatos,
                })
        resultado[nombre_indice] = chunks

        if persistir and chunks:
            coleccion = Chroma(
                collection_name=nombre_indice,
                embedding_function=embeddings,
                persist_directory=str(DIR_CHROMA),
            )
            coleccion.add_texts(
                texts=[c["texto"] for c in chunks],
                metadatas=[c["metadatos"] for c in chunks],
                ids=[c["id"] for c in chunks],
            )

        if persistir:
            DIR_CHUNKS.mkdir(parents=True, exist_ok=True)
            (DIR_CHUNKS / f"{nombre_indice}.json").write_text(
                json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        print(f"Índice '{nombre_indice}': {len(chunks)} chunks")

    return resultado


if __name__ == "__main__":
    ingestar()
