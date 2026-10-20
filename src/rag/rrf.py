"""Reciprocal Rank Fusion: combina rankings sin calibrar puntuaciones (§4.3)."""

import re

RRF_K = 60


def tokenizar(texto: str) -> list[str]:
    return re.findall(r"\w+", texto.lower())


def fusion_rrf(rankings: list[list[str]], k: int) -> list[str]:
    """Ids de los k mejores según la suma de 1 / (RRF_K + posición) en cada ranking."""
    puntuaciones: dict[str, float] = {}
    for ranking in rankings:
        for pos, item_id in enumerate(ranking):
            puntuaciones[item_id] = puntuaciones.get(item_id, 0) + 1 / (RRF_K + pos + 1)
    return sorted(puntuaciones, key=puntuaciones.get, reverse=True)[:k]


def ranking_bm25(bm25, ids: list[str], consulta: str, n: int) -> list[str]:
    scores = bm25.get_scores(tokenizar(consulta))
    return [ids[i] for i in sorted(range(len(ids)), key=lambda i: scores[i], reverse=True)[:n]]
