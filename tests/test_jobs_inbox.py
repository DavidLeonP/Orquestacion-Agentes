"""Bandeja de subidas y avisos de transcripción, sin red ni MySQL."""

from pathlib import Path

import pytest

from src.ingestion import jobs
from src.ingestion.extractors import video


def test_ruta_permitida_solo_dentro_de_la_bandeja(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "DIR_INBOX", tmp_path)
    propio = tmp_path / "7"
    propio.mkdir()
    archivo = propio / "apuntes.txt"
    archivo.write_text("hola", encoding="utf-8")

    assert jobs.ruta_permitida(7, str(archivo)) == archivo.resolve()

    with pytest.raises(ValueError, match="bandeja"):
        jobs.ruta_permitida(7, str(tmp_path / "otro.txt"))
    with pytest.raises(ValueError, match="bandeja"):
        jobs.ruta_permitida(7, "/etc/passwd")


def test_ruta_permitida_rechaza_enlace_fuera(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "DIR_INBOX", tmp_path)
    propio = tmp_path / "7"
    propio.mkdir()
    fuera = tmp_path / "secreto.txt"
    fuera.write_text("no", encoding="utf-8")
    enlace = propio / "atajo.txt"
    enlace.symlink_to(fuera)

    with pytest.raises(ValueError, match="bandeja"):
        jobs.ruta_permitida(7, str(enlace))


def test_transcribir_avisa_cada_segmento(tmp_path, monkeypatch):
    wav = tmp_path / "clase.wav"
    wav.write_bytes(b"wav")
    partes = [tmp_path / "p1.wav", tmp_path / "p2.wav"]
    monkeypatch.setattr(video, "MAX_WHISPER_UPLOAD_BYTES", 1)
    monkeypatch.setattr(video, "_partir_wav_por_duracion", lambda *a, **k: partes)
    monkeypatch.setattr(video, "_transcribir_una", lambda path, language="es": Path(path).stem)

    avisos = []
    texto = video.transcribir_audio(
        wav, on_progress=lambda paso, detalle: avisos.append((paso, detalle))
    )

    assert texto == "p1\n\np2"
    assert avisos == [("asr", "segmento 1/2"), ("asr", "segmento 2/2")]
