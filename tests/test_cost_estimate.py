"""Tests de estimación de chunks/coste (sin red ni embeddings)."""

from src.ingestion.cost_estimate import (
    chars_to_tokens,
    coste_openai,
    coste_usfq,
    estimar_chunks_desde_chars,
    estimar_fuente,
)


def test_estimar_chunks_desde_chars_basico():
    assert estimar_chunks_desde_chars(0) == 0
    assert estimar_chunks_desde_chars(500) == 1
    assert estimar_chunks_desde_chars(1000) == 1
    # 1000 + un paso de 850 → 2 chunks
    assert estimar_chunks_desde_chars(1001) == 2
    assert estimar_chunks_desde_chars(1850) == 2
    assert estimar_chunks_desde_chars(1851) == 3


def test_coste_openai_whisper_domina():
    sources = [
        estimar_fuente(filename="a.pdf", kind="pdf", chars=194_253),
        estimar_fuente(
            filename="clase.mp4",
            kind="video",
            chars=720 * 100,
            duration_sec=100 * 60,
        ),
    ]
    c = coste_openai(sources)
    assert c.whisper_api_usd is not None and c.embed_api_usd is not None
    assert c.whisper_api_usd > c.embed_api_usd
    assert c.total_chunks > 0


def test_coste_usfq_sin_api():
    sources = [
        estimar_fuente(filename="a.pdf", kind="pdf", chars=10_000),
    ]
    c = coste_usfq(sources)
    assert c.total_api_usd == 0.0
    assert c.total_gpu_hours is not None
    assert chars_to_tokens(4) == 1
