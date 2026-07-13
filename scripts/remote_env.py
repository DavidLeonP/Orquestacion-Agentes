"""Carga parámetros SSH / despliegue desde .env para scripts locales."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[1]
load_dotenv(RAIZ / ".env")


@dataclass(frozen=True)
class RemoteConfig:
    host: str
    user: str
    port: int
    password: str
    deploy_path: str
    api_base_url: str
    container_name: str
    docker_image: str

    @property
    def ssh_target(self) -> str:
        return f"{self.user}@{self.host}"


def load_remote_config() -> RemoteConfig:
    host = os.getenv("SSH_HOST", "").strip()
    user = os.getenv("SSH_USER", "root").strip()
    password = os.getenv("SSH_PASSWORD", "")
    if not host:
        raise RuntimeError("Falta SSH_HOST en .env")
    if not password:
        raise RuntimeError("Falta SSH_PASSWORD en .env")
    return RemoteConfig(
        host=host,
        user=user,
        port=int(os.getenv("SSH_PORT", "22")),
        password=password,
        deploy_path=os.getenv("DEPLOY_PATH", "/opt/asistente-ia").rstrip("/"),
        api_base_url=os.getenv(
            "API_BASE_URL", f"http://{host}:8000"
        ).rstrip("/"),
        container_name=os.getenv("CONTAINER_NAME", "asistente-ia-educacion"),
        docker_image=os.getenv("DOCKER_IMAGE", "asistente-ia_asistente:latest"),
    )
