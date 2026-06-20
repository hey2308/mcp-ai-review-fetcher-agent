"""HTTP client for khyati-mcp-server (Google Docs + Gmail MCP)."""

import logging
from typing import Any
from urllib.parse import urljoin

import requests

logger = logging.getLogger(__name__)


class McpServerError(Exception):
    """Raised when the MCP server returns an error response."""


class McpClient:
    """
    Client for https://khyati-mcp-server.onrender.com/

    Tools exposed by the server:
    - GET  /          health check
    - GET  /tools     list tools
    - POST /append_to_doc       { doc_id, content }
    - POST /create_email_draft  { to, subject, body }
    """

    def __init__(self, base_url: str, timeout: int = 60):
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout = timeout

    def _url(self, path: str) -> str:
        return urljoin(self.base_url, path.lstrip("/"))

    def _post(self, path: str, payload: dict) -> dict[str, Any]:
        response = requests.post(
            self._url(path),
            json=payload,
            timeout=self.timeout,
            headers={"Content-Type": "application/json"},
        )
        try:
            data = response.json()
        except Exception:
            data = {"status": "error", "message": response.text}

        if response.status_code >= 400:
            raise McpServerError(
                f"MCP {path} failed ({response.status_code}): {data}"
            )
        if data.get("status") == "error":
            details = data.get("details", "")
            message = data.get("message", str(data))
            if details:
                raise McpServerError(f"{message} — {details}")
            raise McpServerError(message)
        if data.get("status") == "rejected":
            raise McpServerError(data.get("message", "Action rejected by MCP server"))

        return data

    def health_check(self) -> dict[str, Any]:
        response = requests.get(self._url(""), timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def list_tools(self) -> list[dict]:
        response = requests.get(self._url("tools"), timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def append_to_doc(self, doc_id: str, content: str) -> dict[str, Any]:
        return self._post("append_to_doc", {"doc_id": doc_id, "content": content})

    def create_email_draft(self, to: str, subject: str, body: str) -> dict[str, Any]:
        return self._post(
            "create_email_draft",
            {"to": to, "subject": subject, "body": body},
        )


def doc_url_from_id(doc_id: str) -> str:
    return f"https://docs.google.com/document/d/{doc_id}/edit"
