"""Memoria vectorial de aclaraciones del SQL Agent (Chroma).

Colección `clarificaciones_sql_<modelo>`, filtrada por `tenant` (user_id del
docente). Se escribe tras una aclaración humana (HITL) o al sembrar casos
canónicos (p. ej. «año pasado» ≠ `anio_ingreso`). El query_gen las recupera
como pistas antes de generar SQL, para no repetir el mismo error semántico.
"""

from __future__ import annotations

import logging
import uuid

from src.config import UMBRAL_MEMORIA_SQL
from src.llm import get_embeddings
from src.rag.chroma_client import coleccion_vectores, filtro

logger = logging.getLogger("orquestacion.memoria")

MAX_CHARS = 2000
PREFIJO = "clarificaciones_sql"


def _tenant_key(tenant: str | int) -> str:
    return str(tenant)


def archivar(
    tenant: str | int,
    pregunta: str,
    aclaracion: str,
    *,
    leccion: str = "",
    sql_correcto: str = "",
) -> str | None:
    """Persiste una aclaración. Devuelve el id Chroma o None si falló."""
    doc = (
        f"Aclaración: {aclaracion.strip()}\n"
        + (f"Lección: {leccion.strip()}\n" if leccion.strip() else "")
        + (f"SQL correcto (pista): {sql_correcto.strip()}\n" if sql_correcto.strip() else "")
    )[:MAX_CHARS]
    vid = uuid.uuid4().hex
    try:
        coleccion_vectores(PREFIJO).add(
            ids=[vid],
            embeddings=[get_embeddings().embed_query(pregunta)],
            documents=[doc],
            metadatas=[
                {
                    "tenant": _tenant_key(tenant),
                    "peticion": pregunta[:500],
                    "tipo": "aclaracion_sql",
                }
            ],
        )
        return vid
    except Exception as exc:  # noqa: BLE001
        logger.warning("Clarificaciones SQL: no se pudo archivar: %s", exc)
        return None


def recordar(tenant: str | int, pregunta: str, k: int = 3) -> list[str]:
    """Hasta k aclaraciones con similitud coseno >= UMBRAL_MEMORIA_SQL."""
    try:
        res = coleccion_vectores(PREFIJO).query(
            query_embeddings=[get_embeddings().embed_query(pregunta)],
            n_results=k,
            where=filtro(tenant=_tenant_key(tenant)),
            include=["documents", "metadatas", "distances"],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Clarificaciones SQL: no se pudo consultar: %s", exc)
        return []
    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]
    out: list[str] = []
    for doc, meta, dist in zip(docs, metas, dists):
        if 1 - float(dist) < UMBRAL_MEMORIA_SQL:
            continue
        pet = (meta or {}).get("peticion", "")
        out.append(f"Petición parecida: {pet}\n{doc}")
    return out


def seed_anio_pasado(tenant: str | int) -> str | None:
    """Caso canónico del error «año pasado» → anio_ingreso.

    Semántica correcta: filtrar matrículas del último periodo académico
    (`periodos` con mayor `anio_fin`), no el año de ingreso a la carrera.
    """
    return archivar(
        tenant,
        pregunta=(
            "¿Cuáles son los estudiantes que se matricularon el año pasado? "
            "Lista codigo, nombre, carrera y periodo."
        ),
        aclaracion=(
            "«Año pasado» / «último año lectivo» se resuelve con el periodo académico "
            "más reciente en `periodos` (p. ej. MAX(anio_fin) o codigo '2024-2025'), "
            "filtrando estudiantes vía matriculas → ofertas → periodos. "
            "NO uses estudiantes.anio_ingreso: eso es el año de ingreso a la carrera, "
            "no el periodo de matrícula."
        ),
        leccion=(
            "Expresiones temporales relativas (año pasado, semestre pasado, último "
            "periodo) → periodos + matrículas. anio_ingreso solo si preguntan por "
            "cohorte de ingreso."
        ),
        sql_correcto=(
            "SELECT DISTINCT e.codigo, e.nombre, c.codigo AS carrera, p.codigo AS periodo "
            "FROM matriculas m "
            "JOIN estudiantes e ON e.id = m.estudiante_id "
            "JOIN carreras c ON c.id = e.carrera_id "
            "JOIN ofertas o ON o.id = m.oferta_id "
            "JOIN periodos p ON p.id = o.periodo_id "
            "WHERE p.anio_fin = (SELECT MAX(anio_fin) FROM periodos) "
            "ORDER BY e.codigo LIMIT 20"
        ),
    )
