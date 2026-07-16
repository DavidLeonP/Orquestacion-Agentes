"""Model registry: OpenAI o Ollama según recursos (LLM_PROFILE).

El LLM/embeddings son sustituibles; agentes y contratos Pydantic no cambian.
Ollama se usa vía endpoint compatible OpenAI (default http://127.0.0.1:11434/v1).
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
    ollama_base_url: str
    profile: str

    def describe(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "llm_provider": self.llm_provider,
            "llm_model": self.llm_model,
            "embedding_provider": self.embedding_provider,
            "embedding_model": self.embedding_model,
            "ollama_base_url": self.ollama_base_url
            if "ollama" in (self.llm_provider, self.embedding_provider)
            else None,
        }


def resolve_selection(
    profile: str | None = None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    embedding_provider: str | None = None,
    embedding_model: str | None = None,
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

    # Env solo cuenta como override si está definido en el entorno (config ya
    # puede tener default de perfil vía variables; usamos flags explícitos).
    sel = ModelSelection(
        llm_provider=_pick(
            llm_provider, _env_override("LLM_PROVIDER"), defaults["llm_provider"]
        ).lower(),
        llm_model=_pick(llm_model, _env_override("LLM_MODEL"), defaults["llm_model"]),
        embedding_provider=_pick(
            embedding_provider,
            _env_override("EMBEDDING_PROVIDER"),
            defaults["embedding_provider"],
        ).lower(),
        embedding_model=_pick(
            embedding_model,
            _env_override("EMBEDDING_MODEL"),
            defaults["embedding_model"],
        ),
        ollama_base_url=(
            ollama_base_url
            or config.OLLAMA_BASE_URL
            or "http://127.0.0.1:11434/v1"
        ).rstrip("/"),
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
    if sel.llm_provider == "ollama":
        return {
            "model": sel.llm_model,
            "base_url": sel.ollama_base_url,
            "api_key": "ollama",
        }
    return {
        "model": sel.llm_model,
        "api_key": config.OPENAI_API_KEY or None,
    }


def _openai_embed_kwargs(sel: ModelSelection) -> dict[str, Any]:
    if sel.embedding_provider == "ollama":
        return {
            "model": sel.embedding_model,
            "base_url": sel.ollama_base_url,
            "api_key": "ollama",
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


def describe_llm() -> dict[str, Any]:
    return get_selection().describe()


def active_embedding_model() -> str:
    return get_selection().embedding_model
