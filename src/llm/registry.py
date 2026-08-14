"""Model registry: OpenAI, vLLM compatible u Ollama según LLM_PROFILE.

El LLM/embeddings son sustituibles; agentes y contratos Pydantic no cambian.
vLLM y Ollama se usan mediante endpoints compatibles con OpenAI.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from src import config

logger = logging.getLogger("orquestacion.llm")

PROFILES: dict[str, dict[str, str]] = {
    "cloud_openai": {
        "llm_provider": "openai",
        "llm_model": "gpt-4o-mini",
        "embedding_provider": "openai",
        "embedding_model": "text-embedding-3-small",
    },
    "vllm_usfq": {
        "llm_provider": "openai_compatible",
        "llm_model": "deepseek-ai/DeepSeek-V4-Flash-0731",
        "llm_base_url": "http://172.28.230.10:12555/v1",
        "embedding_provider": "openai_compatible",
        "embedding_model": "BAAI/bge-m3",
        "embedding_base_url": "http://172.28.230.10:12556/v1",
    },
    "local_barato": {
        "llm_provider": "ollama",
        "llm_model": "qwen2.5:3b",
        "embedding_provider": "ollama",
        "embedding_model": "nomic-embed-text",
    },
    "local_calidad": {
        "llm_provider": "ollama",
        "llm_model": "qwen2.5:7b",
        "embedding_provider": "ollama",
        "embedding_model": "nomic-embed-text",
    },
}


@dataclass(frozen=True)
class ModelSelection:
    llm_provider: str
    llm_model: str
    embedding_provider: str
    embedding_model: str
    llm_base_url: str | None
    embedding_base_url: str | None
    api_key: str
    profile: str

    def describe(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "llm_provider": self.llm_provider,
            "llm_model": self.llm_model,
            "embedding_provider": self.embedding_provider,
            "embedding_model": self.embedding_model,
            "llm_base_url": self.llm_base_url,
            "embedding_base_url": self.embedding_base_url,
        }


def resolve_selection(
    profile: str | None = None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    embedding_provider: str | None = None,
    embedding_model: str | None = None,
    llm_base_url: str | None = None,
    embedding_base_url: str | None = None,
    api_key: str | None = None,
    ollama_base_url: str | None = None,
) -> ModelSelection:
    """Resuelve perfil + overrides explícitos (env o argumentos)."""
    profile_name = (profile or config.LLM_PROFILE or "cloud_openai").strip().lower()
    defaults = PROFILES.get(profile_name)
    if defaults is None:
        logger.warning("Perfil LLM desconocido '%s'; usando cloud_openai", profile_name)
        profile_name = "cloud_openai"
        defaults = PROFILES[profile_name]

    # Overrides: argumento > env explícito > perfil
    def _pick(arg: str | None, env_val: str | None, profile_val: str) -> str:
        if arg:
            return arg.strip()
        if env_val:
            return env_val.strip()
        return profile_val

    resolved_llm_provider = _pick(
        llm_provider, _env_override("LLM_PROVIDER"), defaults["llm_provider"]
    ).lower()
    resolved_embedding_provider = _pick(
        embedding_provider,
        _env_override("EMBEDDING_PROVIDER"),
        defaults["embedding_provider"],
    ).lower()
    shared_ollama_url = (
        ollama_base_url
        or _env_override("OLLAMA_BASE_URL")
        or config.OLLAMA_BASE_URL
        or "http://127.0.0.1:11434/v1"
    ).rstrip("/")

    def _base_url(
        explicit: str | None,
        env_name: str,
        profile_name: str,
        provider: str,
    ) -> str | None:
        if provider not in {"ollama", "openai_compatible"}:
            return None
        value = explicit or _env_override(env_name) or defaults.get(profile_name)
        if not value and provider == "ollama":
            value = shared_ollama_url
        return value.rstrip("/") if value else None

    # Env solo cuenta como override si está definido en el entorno (config ya
    # puede tener default de perfil vía variables; usamos flags explícitos).
    sel = ModelSelection(
        llm_provider=resolved_llm_provider,
        llm_model=_pick(llm_model, _env_override("LLM_MODEL"), defaults["llm_model"]),
        embedding_provider=resolved_embedding_provider,
        embedding_model=_pick(
            embedding_model,
            _env_override("EMBEDDING_MODEL"),
            defaults["embedding_model"],
        ),
        llm_base_url=_base_url(
            llm_base_url, "LLM_BASE_URL", "llm_base_url", resolved_llm_provider
        ),
        embedding_base_url=_base_url(
            embedding_base_url,
            "EMBEDDING_BASE_URL",
            "embedding_base_url",
            resolved_embedding_provider,
        ),
        api_key=api_key
        or _env_override("OPENAI_COMPAT_API_KEY")
        or config.OPENAI_COMPAT_API_KEY
        or "local",
        profile=profile_name,
    )
    return sel


def _env_override(name: str) -> str | None:
    """Valor de entorno solo si el usuario lo definió (no default de config)."""
    import os

    return os.environ.get(name)


@lru_cache(maxsize=1)
def get_selection() -> ModelSelection:
    return resolve_selection()


def invalidate_registry_cache() -> None:
    get_selection.cache_clear()
    get_chat_model.cache_clear()
    get_embeddings.cache_clear()


def _openai_chat_kwargs(sel: ModelSelection) -> dict[str, Any]:
    if sel.llm_provider in {"ollama", "openai_compatible"}:
        if not sel.llm_base_url:
            raise ValueError(
                f"LLM_BASE_URL es obligatorio para provider {sel.llm_provider}"
            )
        return {
            "model": sel.llm_model,
            "base_url": sel.llm_base_url,
            "api_key": sel.api_key,
        }
    return {
        "model": sel.llm_model,
        "api_key": config.OPENAI_API_KEY or None,
    }


def _openai_embed_kwargs(sel: ModelSelection) -> dict[str, Any]:
    if sel.embedding_provider in {"ollama", "openai_compatible"}:
        if not sel.embedding_base_url:
            raise ValueError(
                "EMBEDDING_BASE_URL es obligatorio para provider "
                f"{sel.embedding_provider}"
            )
        return {
            "model": sel.embedding_model,
            "base_url": sel.embedding_base_url,
            "api_key": sel.api_key,
            # Evita que langchain-openai envíe token IDs (Ollama/vLLM esperan texto).
            "check_embedding_ctx_length": False,
        }
    return {
        "model": sel.embedding_model,
        "api_key": config.OPENAI_API_KEY or None,
    }


@lru_cache(maxsize=4)
def get_chat_model(temperature: float = 0) -> ChatOpenAI:
    sel = get_selection()
    kwargs = _openai_chat_kwargs(sel)
    logger.info(
        "Chat model: provider=%s model=%s", sel.llm_provider, sel.llm_model
    )
    return ChatOpenAI(temperature=temperature, **kwargs)


@lru_cache(maxsize=2)
def get_embeddings() -> OpenAIEmbeddings:
    sel = get_selection()
    kwargs = _openai_embed_kwargs(sel)
    logger.info(
        "Embeddings: provider=%s model=%s",
        sel.embedding_provider,
        sel.embedding_model,
    )
    return OpenAIEmbeddings(**kwargs)


def get_structured_model(schema: Any, temperature: float = 0) -> Any:
    """Modelo con salida Pydantic estable para cada proveedor.

    - ``openai_compatible`` (vLLM): function_calling (response_format JSON falla).
    - ``ollama`` / OpenAI cloud: método por defecto de LangChain.
    """
    llm = get_chat_model(temperature=temperature)
    if get_selection().llm_provider == "openai_compatible":
        return llm.with_structured_output(schema, method="function_calling")
    return llm.with_structured_output(schema)


def describe_llm() -> dict[str, Any]:
    return get_selection().describe()


def active_embedding_model() -> str:
    return get_selection().embedding_model
