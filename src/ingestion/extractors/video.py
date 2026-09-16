"""Extracción de audio y transcripción de vídeo (Whisper cloud o endpoint USFQ).

Flujo:
  vídeo → (ffmpeg) audio → ASR (OpenAI whisper-1 | endpoint compatible)

Por defecto opera en dry_run: solo mide duración/tamaño y estima tokens/coste
sin llamar a ASR ni generar embeddings.
"""

from __future__ import annotations

import logging
import os
import struct
import subprocess
import tempfile
from pathlib import Path

from src.ingestion.extractors.types import ExtractionResult, MediaInventoryItem

logger = logging.getLogger("orquestacion.ingestion.video")

VIDEO_SUFFIXES = {".mp4", ".mkv", ".webm", ".mov", ".m4v"}

# Heurística de densidad de transcripción (clase magistral en español).
CHARS_POR_MINUTO_ESTIMADOS = 720  # ~130 palabras/min × ~5.5 chars
MAX_WHISPER_UPLOAD_BYTES = 24 * 1024 * 1024


def _ffmpeg_bin() -> str:
    """ffmpeg del sistema o binario embebido (imageio-ffmpeg)."""
    import shutil

    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "ffmpeg no encontrado. Instálalo o: pip install imageio-ffmpeg"
        ) from exc


def _ffprobe_bin() -> str | None:
    import shutil

    return shutil.which("ffprobe")


def _mp4_duration_sec(ruta: Path) -> float | None:
    """Lee duración desde el átomo mvhd (sin ffmpeg)."""
    try:
        data = ruta.read_bytes()
    except OSError:
        return None
    idx = data.find(b"mvhd")
    if idx < 0:
        return None
    version = data[idx + 4]
    try:
        if version == 0:
            timescale = struct.unpack(">I", data[idx + 16 : idx + 20])[0]
            duration = struct.unpack(">I", data[idx + 20 : idx + 24])[0]
        else:
            timescale = struct.unpack(">I", data[idx + 20 : idx + 24])[0]
            duration = struct.unpack(">Q", data[idx + 24 : idx + 32])[0]
    except struct.error:
        return None
    if not timescale:
        return None
    return duration / timescale


def _ffprobe_duration_sec(ruta: Path) -> float | None:
    probe = _ffprobe_bin()
    if not probe:
        return None
    try:
        proc = subprocess.run(
            [
                probe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(ruta),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return None


def duration_sec(ruta: Path) -> float | None:
    return _ffprobe_duration_sec(ruta) or _mp4_duration_sec(ruta)


def inventariar_video(ruta: Path) -> MediaInventoryItem:
    dur = duration_sec(ruta)
    return MediaInventoryItem(
        path=str(ruta.resolve()),
        kind="video",
        filename=ruta.name,
        size_bytes=ruta.stat().st_size,
        duration_sec=dur,
        chars_extracted=None,
    )


def estimar_chars_transcripcion(duration_sec: float | None) -> int:
    if not duration_sec or duration_sec <= 0:
        return 0
    return int((duration_sec / 60.0) * CHARS_POR_MINUTO_ESTIMADOS)


def _extraer_audio_wav(video: Path, destino: Path, *, max_seconds: float | None = None) -> None:
    """Extrae audio mono 16 kHz. max_seconds limita la duración (validación rápida)."""
    cmd = [
        _ffmpeg_bin(),
        "-y",
        "-i",
        str(video),
    ]
    if max_seconds and max_seconds > 0:
        cmd.extend(["-t", str(max_seconds)])
    cmd.extend(
        [
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "16000",
            "-ac",
            "1",
            str(destino),
        ]
    )
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(
            "ffmpeg falló al extraer audio.\n"
            f"stderr: {proc.stderr[-800:]}"
        )


def _partir_wav_por_duracion(
    wav: Path, destino_dir: Path, *, segment_sec: int = 600
) -> list[Path]:
    """Parte el WAV en tramos (Whisper API ~25 MB; 10 min mono 16 kHz ≈ seguro)."""
    destino_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(destino_dir / "part_%03d.wav")
    cmd = [
        _ffmpeg_bin(),
        "-y",
        "-i",
        str(wav),
        "-f",
        "segment",
        "-segment_time",
        str(segment_sec),
        "-c",
        "copy",
        pattern,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg segment falló: {proc.stderr[-500:]}")
    parts = sorted(destino_dir.glob("part_*.wav"))
    if not parts:
        raise RuntimeError("No se generaron segmentos de audio")
    return parts


def _whisper_provider() -> str:
    """openai | openai_compatible (infra universidad / vLLM ASR)."""
    return (os.getenv("WHISPER_PROVIDER") or "openai").strip().lower()


def _transcribir_openai(audio_path: Path, *, language: str = "es") -> str:
    from openai import OpenAI

    from src import config

    client = OpenAI(api_key=config.OPENAI_API_KEY or None)
    model = os.getenv("WHISPER_MODEL", "whisper-1")
    with audio_path.open("rb") as fh:
        result = client.audio.transcriptions.create(
            model=model,
            file=fh,
            language=language,
        )
    return getattr(result, "text", None) or str(result)


def _transcribir_compatible(audio_path: Path, *, language: str = "es") -> str:
    """Endpoint OpenAI-compatible (p. ej. faster-whisper detrás de proxy USFQ)."""
    import httpx

    from src import config

    base = (os.getenv("WHISPER_BASE_URL") or "").rstrip("/")
    if not base:
        raise ValueError(
            "WHISPER_BASE_URL es obligatorio cuando WHISPER_PROVIDER=openai_compatible"
        )
    model = os.getenv("WHISPER_MODEL", "whisper-1")
    api_key = (
        os.getenv("WHISPER_API_KEY")
        or config.OPENAI_COMPAT_API_KEY
        or "local"
    )
    url = f"{base}/audio/transcriptions"
    with audio_path.open("rb") as fh:
        resp = httpx.post(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            data={"model": model, "language": language},
            files={"file": (audio_path.name, fh, "audio/wav")},
            timeout=float(os.getenv("WHISPER_TIMEOUT_SEC", "600")),
        )
    resp.raise_for_status()
    payload = resp.json()
    if isinstance(payload, dict) and "text" in payload:
        return str(payload["text"])
    return str(payload)


def _transcribir_una(audio_path: Path, *, language: str = "es") -> str:
    provider = _whisper_provider()
    if provider in {"openai_compatible", "usfq", "vllm"}:
        return _transcribir_compatible(audio_path, language=language)
    return _transcribir_openai(audio_path, language=language)


def transcribir_audio(audio_path: Path, *, language: str = "es") -> str:
    """Transcribe un WAV; parte en segmentos si supera el límite de upload."""
    if audio_path.stat().st_size <= MAX_WHISPER_UPLOAD_BYTES:
        return _transcribir_una(audio_path, language=language)

    with tempfile.TemporaryDirectory(prefix="oa-asr-parts-") as tmp:
        parts = _partir_wav_por_duracion(audio_path, Path(tmp))
        textos = [_transcribir_una(p, language=language) for p in parts]
    return "\n\n".join(t.strip() for t in textos if t and t.strip())


def extraer_video(
    ruta: Path,
    *,
    dry_run: bool = True,
    language: str = "es",
    audio_tmp: Path | None = None,
    max_seconds: float | None = None,
) -> ExtractionResult:
    """Transcribe un vídeo a texto, o solo estima si dry_run=True.

    max_seconds: si se indica, solo se extrae/transcribe ese prefijo (validación).
    """
    inv = inventariar_video(ruta)
    dur_efectiva = inv.duration_sec
    if max_seconds and inv.duration_sec:
        dur_efectiva = min(inv.duration_sec, float(max_seconds))
    elif max_seconds:
        dur_efectiva = float(max_seconds)
    estimado = estimar_chars_transcripcion(dur_efectiva)
    metadatos = {
        "fuente": ruta.name,
        "media_tipo": "video",
        "size_bytes": inv.size_bytes,
        "duration_sec": inv.duration_sec,
        "duration_min": round((inv.duration_sec or 0) / 60.0, 2),
        "asr_provider": _whisper_provider(),
        "asr_model": os.getenv("WHISPER_MODEL", "whisper-1"),
        "max_seconds": max_seconds,
    }
    if dry_run:
        return ExtractionResult(
            filename=f"{ruta.stem}.txt",
            content_text="",
            content_type="video/mp4",
            source_path=str(ruta.resolve()),
            metadatos=metadatos,
            dry_run=True,
            estimated_chars=estimado,
            estimated_duration_sec=dur_efectiva,
        )

    with tempfile.TemporaryDirectory(prefix="oa-asr-") as tmp:
        wav = Path(audio_tmp) if audio_tmp else Path(tmp) / f"{ruta.stem}.wav"
        if audio_tmp is None:
            _extraer_audio_wav(ruta, wav, max_seconds=max_seconds)
        elif not wav.exists():
            raise FileNotFoundError(f"Audio preparado no encontrado: {wav}")
        texto = transcribir_audio(wav, language=language)

    metadatos["chars_transcritos"] = len(texto)
    return ExtractionResult(
        filename=f"{ruta.stem}.txt",
        content_text=texto,
        content_type="text/plain",
        source_path=str(ruta.resolve()),
        metadatos=metadatos,
        dry_run=False,
        estimated_chars=len(texto),
        estimated_duration_sec=dur_efectiva,
    )
