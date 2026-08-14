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
        "LLM_BASE_URL",
        "EMBEDDING_BASE_URL",
        "OPENAI_COMPAT_API_KEY",
        "OLLAMA_BASE_URL",
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


def test_switch_cloud_ignora_urls_compatibles(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://vllm.local/v1")
    monkeypatch.setenv("EMBEDDING_BASE_URL", "http://embed.local/v1")
    sel = resolve_selection(profile="cloud_openai")
    assert sel.llm_base_url is None
    assert sel.embedding_base_url is None


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


def test_perfil_vllm_usfq_usa_urls_separadas():
    sel = resolve_selection(profile="vllm_usfq")
    assert sel.llm_provider == "openai_compatible"
    assert sel.llm_model == "deepseek-ai/DeepSeek-V4-Flash-0731"
    assert sel.llm_base_url == "http://172.28.230.10:12555/v1"
    assert sel.embedding_provider == "openai_compatible"
    assert sel.embedding_model == "BAAI/bge-m3"
    assert sel.embedding_base_url == "http://172.28.230.10:12556/v1"


def test_vllm_admite_overrides_de_urls_y_key(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://chat.local/v1/")
    monkeypatch.setenv("EMBEDDING_BASE_URL", "http://embed.local/v1/")
    monkeypatch.setenv("OPENAI_COMPAT_API_KEY", "test-key")
    sel = resolve_selection(profile="vllm_usfq")
    assert sel.llm_base_url == "http://chat.local/v1"
    assert sel.embedding_base_url == "http://embed.local/v1"
    assert sel.api_key == "test-key"


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
    assert sel.llm_base_url == "http://127.0.0.1:11434/v1"
    assert sel.embedding_base_url == "http://127.0.0.1:11434/v1"


def test_perfil_desconocido_cae_a_cloud():
    sel = resolve_selection(profile="no_existe")
    assert sel.profile == "cloud_openai"
    assert sel.llm_provider == "openai"


def test_describe_incluye_campos_clave():
    d = resolve_selection(profile="local_calidad").describe()
    assert d["llm_provider"] == "ollama"
    assert d["llm_model"]
    assert d["embedding_model"]
