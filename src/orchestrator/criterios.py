"""Criterios objetivos de la rúbrica del docente (notebook §5C: el LLM propone, Python decide).

La rúbrica es material del usuario (índice `rubricas`), así que sus reglas no se
escriben en el código: un LLM las extrae una vez a `CriteriosRubrica` y
`reflexion.verificar_examen` las comprueba gratis en cada intento. La caché se
invalida sola cuando cambia el texto de la rúbrica (clave = hash del texto).
"""

from __future__ import annotations

import hashlib
import logging

from src.agents.base import invocar_estructurado
from src.agents.schemas import CriteriosRubrica
from src.config import EVAL_MODEL
from src.db.models import Chunk
from src.db.session import SessionLocal

logger = logging.getLogger("orquestacion.criterios")

MAX_CHARS_RUBRICA = 8000
# Una entrada por usuario y versión de su rúbrica: crece poco y se pierde al reiniciar
_cache: dict[tuple[int, str], CriteriosRubrica] = {}


def _texto_rubricas(user_id: int) -> str:
    db = SessionLocal()
    try:
        filas = (
            db.query(Chunk.texto)
            .filter(Chunk.user_id == user_id, Chunk.indice == "rubricas")
            .order_by(Chunk.document_id, Chunk.position)
            .all()
        )
    finally:
        db.close()
    texto = "\n".join(t for (t,) in filas)
    if len(texto) > MAX_CHARS_RUBRICA:
        logger.warning("Rúbricas de user=%s truncadas a %d caracteres para extraer criterios",
                       user_id, MAX_CHARS_RUBRICA)
    return texto[:MAX_CHARS_RUBRICA]


def extraer_criterios(texto: str) -> CriteriosRubrica | None:
    """Una llamada al LLM; None si falló (no se cachea: se reintenta en la próxima petición)."""
    fallo = CriteriosRubrica()
    criterios = invocar_estructurado(
        CriteriosRubrica,
        "Extrae de esta rúbrica de exámenes SOLO los criterios de diseño que dice de forma "
        "explícita. Si un criterio no aparece, deja su valor por defecto (no exigir nada).\n"
        "- requiere_seguridad: exige al menos una pregunta de seguridad.\n"
        "- pct_min_numerico: fracción mínima de la puntuación en problemas numéricos.\n"
        "- tipos_minimos: número mínimo de tipos de pregunta distintos.\n\n"
        f"RÚBRICA:\n{texto}",
        EVAL_MODEL,
        fallo,
    )
    return None if criterios is fallo else criterios


def cargar_criterios(user_id: int) -> CriteriosRubrica:
    try:
        texto = _texto_rubricas(user_id)
    except Exception as exc:  # noqa: BLE001 - sin criterios se valida como antes
        logger.warning("Criterios de rúbrica no disponibles: %s", exc)
        return CriteriosRubrica()
    if not texto.strip():
        return CriteriosRubrica()
    clave = (user_id, hashlib.sha256(texto.encode("utf-8")).hexdigest())
    if clave not in _cache:
        criterios = extraer_criterios(texto)
        if criterios is None:
            logger.warning("No se pudieron extraer los criterios de user=%s; se valida sin ellos", user_id)
            return CriteriosRubrica()
        _cache[clave] = criterios
        logger.info("Criterios de rúbrica user=%s: %s", user_id, criterios.model_dump())
    return _cache[clave]
