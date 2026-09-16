"""Smoke de conectividad para los endpoints OpenAI-compatible de la USFQ.

Requiere VPN. No usa MySQL ni ejecuta el orquestador.
"""

from __future__ import annotations

import os
import sys
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

CHAT_BASE_URL = os.getenv(
    "LLM_BASE_URL", "http://172.28.230.10:12555/v1"
).rstrip("/")
EMBEDDING_BASE_URL = os.getenv(
    "EMBEDDING_BASE_URL", "http://172.28.230.10:12556/v1"
).rstrip("/")
CHAT_MODEL = os.getenv("LLM_MODEL", "zai-org/GLM-5.3-Flash")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
API_KEY = os.getenv("OPENAI_COMPAT_API_KEY", "local")


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }


def _models(client: httpx.Client, base_url: str) -> list[str]:
    response = client.get(f"{base_url}/models", headers=_headers())
    response.raise_for_status()
    data = response.json().get("data", [])
    return [str(item["id"]) for item in data if isinstance(item, dict) and item.get("id")]


def _select_model(configured: str, available: list[str], label: str) -> str:
    if configured in available:
        return configured
    if not available:
        raise RuntimeError(f"{label}: /models no devolvió modelos")
    selected = available[0]
    print(
        f"AVISO {label}: '{configured}' no coincide con /models; "
        f"se probará '{selected}'. Actualiza el .env."
    )
    return selected


def main() -> int:
    print(f"Chat:       {CHAT_BASE_URL}")
    print(f"Embeddings: {EMBEDDING_BASE_URL}")
    chat_ok = False
    emb_ok = False
    try:
        with httpx.Client(timeout=60.0) as client:
            try:
                chat_models = _models(client, CHAT_BASE_URL)
                print(f"Modelos chat:       {chat_models}")
                chat_model = _select_model(CHAT_MODEL, chat_models, "chat")
                chat_body: dict[str, Any] = {
                    "model": chat_model,
                    "messages": [
                        {
                            "role": "system",
                            "content": "Responde únicamente con la palabra OK.",
                        },
                        {"role": "user", "content": "Prueba de conectividad."},
                    ],
                    "temperature": 0,
                    "max_tokens": 128,
                }
                chat = client.post(
                    f"{CHAT_BASE_URL}/chat/completions",
                    headers=_headers(),
                    json=chat_body,
                )
                chat.raise_for_status()
                message = chat.json()["choices"][0]["message"]
                content = message.get("content") or message.get("reasoning")
                if not content:
                    raise RuntimeError("chat/completions devolvió un mensaje sin contenido")
                print(f"Chat OK: {content!r}")
                chat_ok = True
            except (httpx.HTTPError, KeyError, IndexError, RuntimeError) as exc:
                print(f"ERROR chat: {exc}", file=sys.stderr)

            try:
                embedding_models = _models(client, EMBEDDING_BASE_URL)
                print(f"Modelos embeddings: {embedding_models}")
                embedding_model = _select_model(
                    EMBEDDING_MODEL, embedding_models, "embeddings"
                )
                embeddings = client.post(
                    f"{EMBEDDING_BASE_URL}/embeddings",
                    headers=_headers(),
                    json={"model": embedding_model, "input": ["prueba de conectividad"]},
                )
                embeddings.raise_for_status()
                vector = embeddings.json()["data"][0]["embedding"]
                print(f"Embeddings OK: dims={len(vector)}")
                emb_ok = True
            except (httpx.HTTPError, KeyError, IndexError, RuntimeError) as exc:
                print(f"ERROR embeddings: {exc}", file=sys.stderr)
                print(
                    "El servicio de embeddings (:12556) no responde. "
                    "Sin él no se puede indexar RAG con bge-m3.",
                    file=sys.stderr,
                )
    except httpx.HTTPError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if chat_ok and emb_ok:
        print("Smoke vLLM USFQ completado.")
        return 0
    if chat_ok:
        print("Smoke parcial: chat OK, embeddings NO.")
        return 2
    print("Smoke vLLM USFQ falló.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
