"""Cliente HTTP hacia la API JWT (sin embeber LangGraph/RAG)."""

from __future__ import annotations

import os
from typing import Any

import httpx


class ApiError(Exception):
    def __init__(self, status_code: int, detail: str, body: Any = None):
        self.status_code = status_code
        self.detail = detail
        self.body = body
        super().__init__(f"HTTP {status_code}: {detail}")


def _base_url() -> str:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    return os.getenv("STREAMLIT_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def _detail_from_response(resp: httpx.Response) -> str:
    try:
        data = resp.json()
    except Exception:
        return resp.text or resp.reason_phrase
    if isinstance(data, dict):
        detail = data.get("detail", data)
        if isinstance(detail, list):
            return "; ".join(str(x) for x in detail)
        return str(detail)
    return str(data)


class ApiClient:
    def __init__(self, token: str | None = None, timeout: float = 120.0):
        self.token = token
        self._client = httpx.Client(base_url=_base_url(), timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def _headers(self) -> dict[str, str]:
        if not self.token:
            return {}
        return {"Authorization": f"Bearer {self.token}"}

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        headers = kwargs.pop("headers", {})
        headers.update(self._headers())
        resp = self._client.request(method, path, headers=headers, **kwargs)
        if resp.status_code == 204:
            return None
        if resp.is_error:
            raise ApiError(resp.status_code, _detail_from_response(resp), body=resp.text)
        if not resp.content:
            return None
        return resp.json()

    # --- Auth / health ---

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def login(self, email: str, password: str) -> dict[str, Any]:
        return self._request(
            "POST", "/auth/login", json={"email": email, "password": password}
        )

    def register(self, email: str, password: str, rol: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/auth/register",
            json={"email": email, "password": password, "rol": rol},
        )

    def me(self) -> dict[str, Any]:
        return self._request("GET", "/auth/me")

    # --- Knowledge ---

    def list_documents(self, indice: str | None = None) -> list[dict[str, Any]]:
        params = {"indice": indice} if indice else None
        return self._request("GET", "/knowledge/documents", params=params)

    def get_document(self, doc_id: int) -> dict[str, Any]:
        return self._request("GET", f"/knowledge/documents/{doc_id}")

    def create_document(
        self,
        indice: str,
        filename: str,
        content_text: str,
        metadatos: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"filename": filename, "content_text": content_text}
        if metadatos is not None:
            body["metadatos"] = metadatos
        return self._request("POST", f"/knowledge/{indice}/documents", json=body)

    def update_document(self, doc_id: int, **fields: Any) -> dict[str, Any]:
        return self._request("PATCH", f"/knowledge/documents/{doc_id}", json=fields)

    def delete_document(self, doc_id: int) -> None:
        self._request("DELETE", f"/knowledge/documents/{doc_id}")

    def ingest(self) -> dict[str, Any]:
        return self._request("POST", "/knowledge/ingest")

    def reprocess(self, doc_id: int) -> dict[str, Any]:
        return self._request("POST", f"/knowledge/documents/{doc_id}/reprocess")

    def list_chunks(self, indice: str | None = None) -> list[dict[str, Any]]:
        params = {"indice": indice} if indice else None
        return self._request("GET", "/knowledge/chunks", params=params)

    # --- Requests / HITL ---

    def create_request(
        self, peticion: str, alumno_id: str | None = None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"peticion": peticion}
        if alumno_id:
            body["alumno_id"] = alumno_id
        return self._request("POST", "/requests", json=body)

    def get_request(self, request_id: int) -> dict[str, Any]:
        return self._request("GET", f"/requests/{request_id}")

    def list_requests(self) -> list[dict[str, Any]]:
        return self._request("GET", "/requests")

    def approve(self, request_id: int, decision: str) -> dict[str, Any]:
        return self._request(
            "POST", f"/requests/{request_id}/approve", json={"decision": decision}
        )

    def events(self, request_id: int) -> list[dict[str, Any]]:
        return self._request("GET", f"/requests/{request_id}/events")
