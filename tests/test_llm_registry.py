"""Tests del model registry (perfiles y overrides)."""

import pytest

from src.llm.registry import PROFILES, invalidate_registry_cache, resolve_selection


@pytest.fixture(autouse=True)
def _clean_registry(monkeypatch):
    for key in (
        "LLM_PROVIDER",
        "LLM_MODEL",
        "EMBEDDING_PROVIDER",
        "EMBEDDING_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)
    invalidate_registry_cache()
    yield
    invalidate_registry_cache()


def test_perfil_cloud_defaults():
    sel = resolve_selection(profile="cloud_openai")
    assert sel.llm_provider == "openai"
    assert sel.llm_model == PROFILES["cloud_openai"]["llm_model"]
    assert sel.embedding_model == PROFILES["cloud_openai"]["embedding_model"]


def test_perfil_local_barato():
    sel = resolve_selection(profile="local_barato")
    assert sel.llm_provider == "ollama"
    assert "qwen" in sel.llm_model
    assert sel.embedding_provider == "ollama"
    assert sel.embedding_model == "nomic-embed-text"


def test_perfil_local_calidad():
    sel = resolve_selection(profile="local_calidad")
    assert sel.llm_provider == "ollama"
    assert sel.llm_model == "qwen2.5:7b"


def test_override_explicito_pisa_perfil():
    sel = resolve_selection(
        profile="cloud_openai",
        llm_provider="ollama",
        llm_model="mistral:7b",
        embedding_provider="ollama",
        embedding_model="nomic-embed-text",
        ollama_base_url="http://127.0.0.1:11434/v1",
    )
    assert sel.llm_provider == "ollama"
    assert sel.llm_model == "mistral:7b"


def test_perfil_desconocido_cae_a_cloud():
    sel = resolve_selection(profile="no_existe")
    assert sel.profile == "cloud_openai"
    assert sel.llm_provider == "openai"


def test_describe_incluye_campos_clave():
    d = resolve_selection(profile="local_calidad").describe()
    assert d["llm_provider"] == "ollama"
    assert d["llm_model"]
    assert d["embedding_model"]
