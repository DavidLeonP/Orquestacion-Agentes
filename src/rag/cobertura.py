"""Cobertura documental: ¿la petición está anclada a la KB vectorial de la sesión?

El retriever híbrido siempre devuelve top-k si hay chunks (BM25/RRF), aunque el
tema no tenga relación. Este módulo aplica un umbral de relevancia (coseno o
solapamiento léxico) para que los Guardrails y el router puedan rechazar
peticiones fuera de contexto en lugar de inventar contenido.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.config import (
    UMBRAL_COBERTURA_KB,
    UMBRAL_COBERTURA_LEX,
    UMBRAL_COBERTURA_SEM_FUERTE,
)
from src.observability.trazas import registrar_evento
from src.rag.context import anotar_fuentes, rag_user_id_actual
from src.rag.mysql_store import obtener_retriever
from src.rag.rrf import tokenizar

# Índices a consultar según el agente destino del orquestador.
INDICES_POR_AGENTE: dict[str, tuple[str, ...]] = {
    "exam_generator": ("apuntes", "examenes", "rubricas"),
    "curriculum": ("curriculo", "apuntes"),
    "rubric": ("rubricas", "curriculo"),
    "tutor": ("apuntes", "curriculo"),
}

_STOP = frozenset(
    "a al algo alguna algunas alguno algunos ante antes aquel aquella aquellas "
    "aquellos aqui aquí abajo arriba asi así aunque bajo bien cada casi "
    "como cómo con contra cual cuales cualquier cuando cuándo de del desde "
    "donde dónde dos el ella ellas ellos en entre era eran es esa esas ese eso "
    "esos esta estas este esto estos fin fue fueron ha han hasta hay la las le "
    "les lo los mas más me mi mis mucha muchas mucho muchos muy nada ni no nos "
    "o os otra otras otro otros para pero poco por porque que qué se ser si sí "
    "sin sobre su sus te tener ti tiene tienen toda todas todo todos tu tus un "
    "una unas unos usted ustedes va van y ya yo del al por con sin sobre entre "
    "hasta desde hacia durante mediante según segun tras quiero dame hazme haz "
    "genera crea elabora diseña disena prepara redacta propon propón sobre "
    "examen preguntas pregunta complejas compleja".split()
)

MENSAJE_FUERA_CONTEXTO = (
    "No puedo atender esta petición con el material de la sesión actual: "
    "no hay evidencia suficiente en la base documental vectorial asociada a "
    "tu usuario. Reformula la consulta usando temas, conceptos o unidades "
    "que figuren en tus apuntes, exámenes, rúbricas o currículo cargados. "
    "No inventaré contenido ajeno a esa documentación."
)


@dataclass
class CoberturaKB:
    suficiente: bool
    motivo: str = ""
    score: float = 0.0
    fuentes: list[str] = field(default_factory=list)
    asignatura: str | None = None
    curso: str | None = None
    temas_sugeridos: list[str] = field(default_factory=list)
    resumen_para_prompt: str = ""

    def mensaje_rechazo(self) -> str:
        detalle = f" ({self.motivo})" if self.motivo else ""
        return MENSAJE_FUERA_CONTEXTO + detalle


def _palabras_clave(texto: str) -> set[str]:
    return {t for t in tokenizar(texto) if len(t) > 2 and t not in _STOP}


def _solapamiento(consulta: str, textos: list[str]) -> float:
    q = _palabras_clave(consulta)
    if not q:
        return 0.0
    corpus = _palabras_clave(" ".join(textos))
    if not corpus:
        return 0.0
    return len(q & corpus) / len(q)


def _meta_frecuente(chunks: list[dict], clave: str) -> str | None:
    counts: dict[str, int] = {}
    for c in chunks:
        v = (c.get("metadatos") or {}).get(clave)
        if isinstance(v, str) and v.strip():
            counts[v.strip()] = counts.get(v.strip(), 0) + 1
    if not counts:
        return None
    return max(counts, key=counts.get)


def _temas_desde_chunks(chunks: list[dict], limite: int = 5) -> list[str]:
    temas: list[str] = []
    vistos: set[str] = set()
    for c in chunks:
        m = c.get("metadatos") or {}
        for clave in ("tema", "unidad", "titulo"):
            v = m.get(clave)
            if isinstance(v, str) and v.strip():
                k = v.strip().lower()
                if k not in vistos:
                    vistos.add(k)
                    temas.append(v.strip())
        if len(temas) >= limite:
            break
    if len(temas) >= 2:
        return temas[:limite]
    # Fallback: primeras frases útiles del texto recuperado
    for c in chunks:
        texto = (c.get("texto") or "").strip()
        if not texto:
            continue
        linea = re.split(r"[\n.]", texto, maxsplit=1)[0].strip()
        if 12 <= len(linea) <= 80:
            k = linea.lower()
            if k not in vistos:
                vistos.add(k)
                temas.append(linea)
        if len(temas) >= limite:
            break
    return temas[:limite]


def evaluar_cobertura(
    consulta: str,
    indices: tuple[str, ...] | list[str],
    *,
    k: int = 4,
    umbral: float | None = None,
) -> CoberturaKB:
    """Evalúa si la consulta está respaldada por la KB del usuario en sesión."""
    umbral = UMBRAL_COBERTURA_KB if umbral is None else umbral
    user_id = rag_user_id_actual()
    if user_id is None:
        # Tests / CLI sin usuario: no bloqueamos (el caller decide).
        return CoberturaKB(
            suficiente=True,
            motivo="sin user_id RAG; se omite el guardrail de cobertura",
            score=1.0,
        )

    chunks: list[dict] = []
    scores_sem: list[float] = []
    kb_vacia = True
    for indice in indices:
        retriever = obtener_retriever(user_id, indice)
        if retriever.chunks:
            kb_vacia = False
        # Solo similitud coseno (Chroma/MySQL) cuenta como score semántico.
        # El BM25 relativo de buscar_con_score NO sirve de umbral: el top-1
        # queda en 1.0 aunque la consulta no tenga solape real.
        try:
            sem = retriever._ranking_semantico_scored(consulta, k)  # noqa: SLF001
        except Exception:  # noqa: BLE001
            sem = []
        por_id = {c["id"]: c for c in retriever.chunks}
        for cid, sim in sem:
            chunk = por_id.get(cid)
            if chunk is None:
                continue
            chunks.append(chunk)
            scores_sem.append(float(sim))
        # Snippets de respaldo vía híbrido (solo para metadatos / prompt).
        for chunk, _ in retriever.buscar_con_score(consulta, k=k):
            if chunk not in chunks:
                chunks.append(chunk)

    if kb_vacia:
        cobertura = CoberturaKB(
            suficiente=False,
            motivo="la base documental de la sesión está vacía",
            score=0.0,
        )
        registrar_evento("guardrail_cobertura", suficiente=False, motivo=cobertura.motivo)
        return cobertura

    if not chunks:
        cobertura = CoberturaKB(
            suficiente=False,
            motivo="sin resultados en los índices consultados",
            score=0.0,
        )
        registrar_evento("guardrail_cobertura", suficiente=False, motivo=cobertura.motivo)
        return cobertura

    score_sem = max(scores_sem) if scores_sem else 0.0
    score_lex = _solapamiento(consulta, [c.get("texto", "") for c in chunks])
    # Semántica fuerte, léxico alto, o ambos medios. El top-1 HNSW (~0.3) solo
    # no basta: Chroma siempre devuelve vecinos.
    score = max(score_sem, score_lex)
    suficiente = (
        score_sem >= UMBRAL_COBERTURA_SEM_FUERTE
        or score_lex >= max(umbral, UMBRAL_COBERTURA_LEX)
        or (score_sem >= umbral and score_lex >= UMBRAL_COBERTURA_LEX)
    )
    fuentes = [
        str((c.get("metadatos") or {}).get("fuente") or "").strip()
        for c in chunks
        if (c.get("metadatos") or {}).get("fuente")
    ]
    fuentes = list(dict.fromkeys(f for f in fuentes if f))
    anotar_fuentes(fuentes)

    motivo = (
        f"sem={score_sem:.2f} lex={score_lex:.2f} (umbral_sem={umbral:.2f}, "
        f"lex>={UMBRAL_COBERTURA_LEX:.2f} o sem>={UMBRAL_COBERTURA_SEM_FUERTE:.2f})"
        if suficiente
        else (
            f"sem={score_sem:.2f} lex={score_lex:.2f} insuficiente "
            f"(tema no respaldado por la KB de la sesión)"
        )
    )
    snippets = []
    for c in chunks[:3]:
        m = c.get("metadatos") or {}
        fuente = m.get("fuente", "?")
        texto = (c.get("texto") or "").strip().replace("\n", " ")
        snippets.append(f"[{fuente}] {texto[:280]}")

    cobertura = CoberturaKB(
        suficiente=suficiente,
        motivo=motivo,
        score=score,
        fuentes=fuentes,
        asignatura=_meta_frecuente(chunks, "asignatura"),
        curso=_meta_frecuente(chunks, "curso"),
        temas_sugeridos=_temas_desde_chunks(chunks),
        resumen_para_prompt="\n".join(snippets),
    )
    registrar_evento(
        "guardrail_cobertura",
        suficiente=suficiente,
        score=round(score, 4),
        umbral=umbral,
        fuentes=fuentes[:8],
        indices=list(indices),
    )
    return cobertura


def indices_para_agente(agente: str) -> tuple[str, ...]:
    return INDICES_POR_AGENTE.get(agente, ("apuntes", "examenes", "rubricas", "curriculo"))
