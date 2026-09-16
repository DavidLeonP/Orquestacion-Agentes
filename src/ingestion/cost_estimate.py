"""Estimación de coste computacional de embeddings (sin llamar al embedder).

Compara perfil cloud OpenAI vs infraestructura universidad (vLLM / bge-m3).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from langchain_text_splitters import RecursiveCharacterTextSplitter

# Precios OpenAI publicados (referencia 2026). Ajustar si cambian.
OPENAI_EMBED_USD_PER_1M = {
    "text-embedding-3-small": 0.02,
    "text-embedding-3-large": 0.13,
    "text-embedding-ada-002": 0.10,
}
OPENAI_WHISPER_USD_PER_MIN = 0.006
OPENAI_GPT4O_MINI_TRANSCRIBE_USD_PER_MIN = 0.003

# Dimensiones típicas por modelo (persistencia MySQL / memoria).
EMBED_DIMS = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
    "BAAI/bge-m3": 1024,
    "nomic-embed-text": 768,
}

# Heurísticas de infraestructura on-prem (documentar como supuestos).
ASR_REALTIME_FACTOR_GPU = 0.25  # 1 h audio ≈ 0.25 h GPU (faster-whisper)
EMBED_CHUNKS_PER_SEC_GPU = 80.0  # bge-m3 batch en GPU modest
GPU_WATTS = 300.0
KWH_USD = 0.12  # tarifa eléctrica ilustrativa


@dataclass
class SourceEstimate:
    filename: str
    kind: str
    chars: int
    tokens_approx: int
    chunks: int
    duration_sec: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CostBreakdown:
    profile: str
    embedding_model: str
    embedding_dims: int
    total_chars: int
    total_tokens_approx: int
    total_chunks: int
    embed_api_usd: float | None
    whisper_api_usd: float | None
    total_api_usd: float | None
    asr_gpu_hours: float | None
    embed_gpu_hours: float | None
    total_gpu_hours: float | None
    energy_kwh: float | None
    energy_usd: float | None
    vector_storage_mb: float
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def chars_to_tokens(chars: int) -> int:
    """Aprox. tokens para ES/EN (~4 chars/token). Suficiente para presupuestos."""
    return max(0, (chars + 3) // 4)


def estimar_chunks(texto: str, *, chunk_size: int = 1000, chunk_overlap: int = 150) -> int:
    if not texto:
        return 0
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size, chunk_overlap=chunk_overlap
    )
    return len(splitter.split_text(texto) or [texto])


def estimar_chunks_desde_chars(
    chars: int, *, chunk_size: int = 1000, chunk_overlap: int = 150
) -> int:
    """Estimación sin texto real (dry-run vídeo).

    Avance efectivo ≈ chunk_size - overlap; el último trozo cierra el conteo.
    """
    if chars <= 0:
        return 0
    if chars <= chunk_size:
        return 1
    step = max(1, chunk_size - chunk_overlap)
    return 1 + (chars - chunk_size + step - 1) // step


def _vector_storage_mb(chunks: int, dims: int) -> float:
    # float32 por dimensión + overhead ORM/JSON ~1.3x
    bytes_raw = chunks * dims * 4 * 1.3
    return round(bytes_raw / (1024 * 1024), 3)


def estimar_fuente(
    *,
    filename: str,
    kind: str,
    chars: int,
    duration_sec: float | None = None,
    texto: str | None = None,
) -> SourceEstimate:
    if texto is not None and texto:
        chunks = estimar_chunks(texto)
        chars = len(texto)
    else:
        chunks = estimar_chunks_desde_chars(chars)
    return SourceEstimate(
        filename=filename,
        kind=kind,
        chars=chars,
        tokens_approx=chars_to_tokens(chars),
        chunks=chunks,
        duration_sec=duration_sec,
    )


def coste_openai(
    sources: list[SourceEstimate],
    *,
    embedding_model: str = "text-embedding-3-small",
    whisper_usd_per_min: float = OPENAI_WHISPER_USD_PER_MIN,
) -> CostBreakdown:
    total_chars = sum(s.chars for s in sources)
    total_tokens = sum(s.tokens_approx for s in sources)
    total_chunks = sum(s.chunks for s in sources)
    video_min = sum((s.duration_sec or 0.0) for s in sources if s.kind == "video") / 60.0
    price = OPENAI_EMBED_USD_PER_1M.get(embedding_model, 0.02)
    embed_usd = (total_tokens / 1_000_000.0) * price
    whisper_usd = video_min * whisper_usd_per_min
    dims = EMBED_DIMS.get(embedding_model, 1536)
    notes = [
        f"Embeddings API: ${price}/1M tokens ({embedding_model}).",
        f"ASR API: ${whisper_usd_per_min}/min (whisper-1 o equivalente).",
        "No incluye coste de chat/razonamiento de agentes tras el ingest.",
        "Tokens aproximados (chars/4); la factura real usa el tokenizer de OpenAI.",
    ]
    return CostBreakdown(
        profile="cloud_openai",
        embedding_model=embedding_model,
        embedding_dims=dims,
        total_chars=total_chars,
        total_tokens_approx=total_tokens,
        total_chunks=total_chunks,
        embed_api_usd=round(embed_usd, 6),
        whisper_api_usd=round(whisper_usd, 4),
        total_api_usd=round(embed_usd + whisper_usd, 4),
        asr_gpu_hours=None,
        embed_gpu_hours=None,
        total_gpu_hours=None,
        energy_kwh=None,
        energy_usd=None,
        vector_storage_mb=_vector_storage_mb(total_chunks, dims),
        notes=notes,
    )


def coste_usfq(
    sources: list[SourceEstimate],
    *,
    embedding_model: str = "BAAI/bge-m3",
    asr_realtime_factor: float = ASR_REALTIME_FACTOR_GPU,
    embed_chunks_per_sec: float = EMBED_CHUNKS_PER_SEC_GPU,
    gpu_watts: float = GPU_WATTS,
    kwh_usd: float = KWH_USD,
) -> CostBreakdown:
    total_chars = sum(s.chars for s in sources)
    total_tokens = sum(s.tokens_approx for s in sources)
    total_chunks = sum(s.chunks for s in sources)
    audio_hours = sum((s.duration_sec or 0.0) for s in sources if s.kind == "video") / 3600.0
    asr_gpu_h = audio_hours * asr_realtime_factor
    embed_gpu_h = (total_chunks / embed_chunks_per_sec) / 3600.0 if total_chunks else 0.0
    total_gpu_h = asr_gpu_h + embed_gpu_h
    energy_kwh = total_gpu_h * (gpu_watts / 1000.0)
    energy_usd = energy_kwh * kwh_usd
    dims = EMBED_DIMS.get(embedding_model, 1024)
    notes = [
        "Sin coste API de OpenAI: ASR + embeddings en infraestructura universidad.",
        f"ASR: factor tiempo-real ×{asr_realtime_factor} (faster-whisper / GPU).",
        f"Embeddings: ~{embed_chunks_per_sec} chunks/s en GPU ({embedding_model}).",
        f"Energía ilustrativa: {gpu_watts} W × ${kwh_usd}/kWh (sin amortización GPU).",
        "Amortización de servidor/GPU y ops no incluidas; suelen dominar el TCO.",
    ]
    return CostBreakdown(
        profile="vllm_usfq",
        embedding_model=embedding_model,
        embedding_dims=dims,
        total_chars=total_chars,
        total_tokens_approx=total_tokens,
        total_chunks=total_chunks,
        embed_api_usd=0.0,
        whisper_api_usd=0.0,
        total_api_usd=0.0,
        asr_gpu_hours=round(asr_gpu_h, 4),
        embed_gpu_hours=round(embed_gpu_h, 6),
        total_gpu_hours=round(total_gpu_h, 4),
        energy_kwh=round(energy_kwh, 4),
        energy_usd=round(energy_usd, 4),
        vector_storage_mb=_vector_storage_mb(total_chunks, dims),
        notes=notes,
    )


def comparar_perfiles(sources: list[SourceEstimate]) -> dict[str, Any]:
    openai = coste_openai(sources)
    usfq = coste_usfq(sources)
    return {
        "fuentes": [s.to_dict() for s in sources],
        "cloud_openai": openai.to_dict(),
        "vllm_usfq": usfq.to_dict(),
        "resumen": {
            "chunks_totales": openai.total_chunks,
            "tokens_approx": openai.total_tokens_approx,
            "api_usd_openai": openai.total_api_usd,
            "gpu_hours_usfq": usfq.total_gpu_hours,
            "energy_usd_usfq": usfq.energy_usd,
            "dominante_openai": "ASR (Whisper), no embeddings",
            "dominante_usfq": "ASR en GPU; embeddings casi despreciables",
        },
    }
