"""Async HTTP client wrapping the zotero_write_api_plugin endpoints."""

from __future__ import annotations

import os
from typing import Any

import httpx


class ZoteroWriteError(RuntimeError):
    """Raised when the Zotero write plugin returns an error response."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        response_json: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.response_json = response_json

    def __str__(self) -> str:  # pragma: no cover - trivial
        if self.status_code is not None:
            return f"[{self.status_code}] {self.message}"
        return self.message


class ZoteroWriteClient:
    """Async client for the local Zotero write plugin HTTP endpoints."""

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = (
            base_url
            or os.environ.get("ZOTERO_LOCAL_API_BASE", "http://127.0.0.1:23119")
        ).rstrip("/")
        self.timeout = (
            timeout
            if timeout is not None
            else float(os.environ.get("ZOTERO_WRITE_TIMEOUT", "60"))
        )
        self._client = client
        self._owns_client = client is None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
            self._owns_client = True
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base_url}{path}"

    @staticmethod
    def _parse_json(response: httpx.Response) -> dict[str, Any] | None:
        try:
            data = response.json()
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        client = await self._get_client()
        response = await client.post(self._url(path), json=payload)
        data = self._parse_json(response)
        if response.status_code < 200 or response.status_code >= 300:
            msg = (
                (data or {}).get("error")
                if isinstance(data, dict)
                else None
            ) or f"HTTP {response.status_code} from {path}"
            raise ZoteroWriteError(
                msg, status_code=response.status_code, response_json=data
            )
        if data is None:
            raise ZoteroWriteError(
                f"Non-JSON response from {path}",
                status_code=response.status_code,
                response_json=None,
            )
        if data.get("success") is False:
            raise ZoteroWriteError(
                data.get("error") or "Zotero write plugin reported failure",
                status_code=response.status_code,
                response_json=data,
            )
        return data

    async def version(self) -> dict[str, Any]:
        client = await self._get_client()
        response = await client.get(self._url("/version"))
        data = self._parse_json(response)
        if response.status_code < 200 or response.status_code >= 300:
            msg = (
                (data or {}).get("error")
                if isinstance(data, dict)
                else None
            ) or f"HTTP {response.status_code} from /version"
            raise ZoteroWriteError(
                msg, status_code=response.status_code, response_json=data
            )
        if data is None:
            raise ZoteroWriteError(
                "Non-JSON response from /version",
                status_code=response.status_code,
            )
        if data.get("success") is False:
            raise ZoteroWriteError(
                data.get("error") or "Zotero write plugin reported failure",
                status_code=response.status_code,
                response_json=data,
            )
        return data

    async def import_by_identifier(
        self, identifier: str, collection_key: str | None = None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "operation": "import_by_identifier",
            "identifier": identifier,
        }
        if collection_key is not None:
            payload["collection_key"] = collection_key
        return await self._post("/write", payload)

    async def attach_note(self, item_key: str, note_html: str) -> dict[str, Any]:
        payload = {
            "operation": "attach_note",
            "item_key": item_key,
            "note": note_html,
        }
        return await self._post("/write", payload)

    async def import_pdf(
        self,
        file_name: str,
        file_bytes_base64: str,
        collection_key: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "operation": "import_pdf",
            "file_name": file_name,
            "file_bytes_base64": file_bytes_base64,
        }
        if collection_key is not None:
            payload["collection_key"] = collection_key
        return await self._post("/write", payload)

    async def attach_file(
        self,
        item_key: str,
        file_name: str,
        file_bytes_base64: str,
        title: str,
    ) -> dict[str, Any]:
        payload = {
            "item_key": item_key,
            "title": title,
            "file_name": file_name,
            "file_bytes_base64": file_bytes_base64,
        }
        return await self._post("/attach", payload)
