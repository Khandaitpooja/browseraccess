from __future__ import annotations

import base64
import logging

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
            response_body = serialize_body(response.content, headers.get("content-type", ""))
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


def normalize_response_headers(headers: httpx.Headers) -> dict[str, str]:
    result: dict[str, str] = {}
    set_cookie_values: list[str] = []

    for key, value in headers.multi_items():
        lower = key.lower()
        if lower in HOP_BY_HOP_HEADERS:
            continue
        if lower == "set-cookie":
            set_cookie_values.append(value)
            continue
        result[lower] = value

    if set_cookie_values:
        result["set-cookie"] = "\n".join(set_cookie_values)

    return result


def serialize_body(body: bytes, content_type: str) -> str:
    lowered = content_type.lower()
    if "text/" in lowered or "json" in lowered or "javascript" in lowered or "xml" in lowered:
        return body.decode("utf-8", errors="ignore")
    return BINARY_PREFIX + base64.b64encode(body).decode("ascii")
