from __future__ import annotations

import base64
import logging
from typing import Any

import httpx

from common.schemas import ProxyRequestMessage, ProxyResponseMessage

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}

BINARY_PREFIX = "__base64__"


class ProxyHandler:
    """Handles each proxied HTTP request from server to local target camera."""

    def __init__(self, timeout_seconds: float = 20.0) -> None:
        self.timeout_seconds = timeout_seconds

    async def handle(self, message: ProxyRequestMessage) -> ProxyResponseMessage:
        target_url = f"http://{message.target}{message.path}"
        if message.query:
            target_url = f"{target_url}?{message.query}"

        safe_headers = {
            key: value
            for key, value in message.headers.items()
            if key.lower() not in HOP_BY_HOP_HEADERS
        }

        body = message.body.encode("utf-8") if message.body else None

        try:
            async with httpx.AsyncClient(timeout=min(message.timeout_seconds, self.timeout_seconds), follow_redirects=True) as client:
                response = await client.request(
                    method=message.method,
                    url=target_url,
                    headers=safe_headers,
                    content=body,
                )

            headers = normalize_response_headers(response.headers)
            response_body = serialize_body(response)
            return ProxyResponseMessage(
                id=message.id,
                status=response.status_code,
                headers=headers,
                body=response_body,
            )
        except Exception as exc:  # noqa: BLE001
            logging.exception("proxy_fetch_failed", extra={"target": message.target, "path": message.path})
            return ProxyResponseMessage(
                id=message.id,
                status=502,
                headers={"content-type": "text/plain; charset=utf-8"},
                body="",
                error=f"Target request failed: {exc}",
            )


def normalize_response_headers(headers: httpx.Headers) -> dict[str, Any]:
    """Convert h2/h3 headers to safe downstream object and preserve cookies."""
    result: dict[str, Any] = {}
    set_cookie_values: list[str] = []

    for key, value in headers.multi_items():
        lower = key.lower()
        if lower in HOP_BY_HOP_HEADERS:
            continue
        if lower == "set-cookie":
            set_cookie_values.append(value)
            continue
        if lower == "content-length":
            continue
        result[lower] = value

    if set_cookie_values:
        result["set-cookie"] = set_cookie_values

    return result


def serialize_body(response: httpx.Response) -> str:
    """Serialize agent response body to text or base64 prefix for binary data."""
    content_type = response.headers.get("content-type", "")
    lowered = content_type.lower()

    if "text/" in lowered or "json" in lowered or "javascript" in lowered or "xml" in lowered:
        # Preserve HTTPX-decoded text (charset-aware) when possible
        try:
            return response.text
        except Exception:
            return response.content.decode("utf-8", errors="replace")

    # Return base64 for binary payloads
    return BINARY_PREFIX + base64.b64encode(response.content).decode("ascii")
