"""Registro de modelos LLM / embeddings."""

from src.llm.registry import (
    PROFILES,
    ModelSelection,
    active_embedding_model,
    describe_llm,
    get_chat_model,
    get_embeddings,
    get_selection,
    invalidate_registry_cache,
    resolve_selection,
)

__all__ = [
    "PROFILES",
    "ModelSelection",
    "active_embedding_model",
    "describe_llm",
    "get_chat_model",
    "get_embeddings",
    "get_selection",
    "invalidate_registry_cache",
    "resolve_selection",
]
