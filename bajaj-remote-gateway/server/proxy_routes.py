from __future__ import annotations

import asyncio
import base64
import logging
import re
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, Response

from schemas import ProxyRequestMessage, ProxyResponseMessage

from connection_manager import ConnectionManager
from ws_manager import PendingRequestManager

router = APIRouter(tags=["proxy"])

# Headers that must not be forwarded as per RFC 2616 Section 13.5.1.
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

TARGET_NAME_RE = re.compile(r"^[a-zA-Z0-9](?:[a-zA-Z0-9\-\.]{0,253}[a-zA-Z0-9])?$")


def valid_target(target: str) -> bool:
    """Validate a target host with TCP port to prevent URL injections."""
    if not target:
        return False
    if ":" not in target:
        return False

    host, _, port_str = target.rpartition(":")
    if not host or not port_str or not port_str.isdigit():
        return False

    port = int(port_str)
    if port < 1 or port > 65535:
        return False

    try:
        ip_address(host)
        return True
    except ValueError:
        pass

    if host.lower() == "localhost":
        return True

    return bool(TARGET_NAME_RE.match(host))


class ProxyService:
    """Service driver for HTTP proxy inbound requests to agent websocket tunnels."""

    def __init__(self, connections: ConnectionManager, pending: PendingRequestManager, timeout_seconds: float = 20.0):
        self.connections = connections
        self.pending = pending
        self.timeout_seconds = timeout_seconds

    async def process_request(self, request: Request, target: str, path: str) -> Response:
        if not valid_target(target):
            logging.warning("invalid_target", extra={"target": target, "path": path})
            raise HTTPException(status_code=400, detail="Invalid target format")

        agent_id = await self._resolve_agent_id(request)
        agent = await self.connections.get(agent_id)
        if not agent:
            logging.warning("agent_not_connected", extra={"agent_id": agent_id, "target": target, "path": path})
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not connected")

        request_id = str(uuid4())
        body_bytes = await request.body()
        headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP_HEADERS}

        filtered_query_items = [(k, v) for k, v in request.query_params.multi_items() if k != "agent_id"]
        filtered_query = urlencode(filtered_query_items)

        proxy_message = ProxyRequestMessage(
            id=request_id,
            method=request.method,
            target=target,
            path=f"/{path}" if not path.startswith("/") else path,
            query=filtered_query,
            headers=headers,
            body=body_bytes.decode("utf-8", errors="ignore") if body_bytes else None,
            timeout_seconds=self.timeout_seconds,
        )

        future = await self.pending.create(request_id, agent_id)
        try:
            await agent.websocket.send_json(proxy_message.model_dump())
        except Exception as exc:  # noqa: BLE001
            await self.pending.cleanup(request_id)
            logging.exception("agent_send_failed", extra={"agent_id": agent_id, "request_id": request_id, "target": target, "path": path})
            raise HTTPException(status_code=502, detail="Failed to forward request to agent") from exc

        try:
            response_message = await asyncio.wait_for(future, timeout=self.timeout_seconds)
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
                await self.pending.fail(request_id, "Agent timeout")
                logging.warning("agent_response_timeout", extra={"agent_id": agent_id, "request_id": request_id, "target": target, "path": path})
                raise HTTPException(status_code=504, detail="Agent response timeout") from exc
            elif isinstance(exc, asyncio.CancelledError):
                await self.pending.fail(request_id, "Agent timeout")
                logging.warning("agent_response_timeout", extra={"agent_id": agent_id, "request_id": request_id, "target": target, "path": path})
                raise HTTPException(status_code=504, detail="Agent response timeout") from exc
            else:
                logging.exception("agent_response_error", extra={"agent_id": agent_id, "request_id": request_id, "target": target, "path": path})
                raise HTTPException(status_code=502, detail=str(exc)) from exc

        if response_message.error:
            logging.error("proxy_error_from_agent", extra={"agent_id": agent_id, "request_id": request_id, "target": target, "path": path, "error": response_message.error})
            raise HTTPException(status_code=502, detail=response_message.error)

        return build_http_response(response_message, target)

    async def _resolve_agent_id(self, request: Request) -> str:
        explicit_agent = request.query_params.get("agent_id") or request.headers.get("x-agent-id")
        if explicit_agent:
            return explicit_agent

        agents = await self.connections.list_agents()
        if not agents:
            raise HTTPException(status_code=404, detail="No agents connected")
        if len(agents) == 1:
            return agents[0]
        raise HTTPException(
            status_code=400,
            detail="Multiple agents connected. Provide ?agent_id=<agent_id>",
        )


def build_http_response(proxy_response: ProxyResponseMessage, target: str) -> Response:
    """Serialize a ProxyResponseMessage into a FastAPI Response for browser."""
    content_type = str(proxy_response.headers.get("content-type", ""))
    body_text = proxy_response.body or ""
    if body_text.startswith(BINARY_PREFIX):
        body_bytes = base64.b64decode(body_text[len(BINARY_PREFIX) :])
    else:
        if "text/html" in content_type.lower():
            body_text = rewrite_html_paths(body_text, target)
        body_bytes = body_text.encode("utf-8", errors="ignore")

    raw_headers = {k: v for k, v in proxy_response.headers.items() if k.lower() not in HOP_BY_HOP_HEADERS and k.lower() != "content-encoding"}

    response = Response(content=body_bytes, status_code=proxy_response.status, media_type=content_type or "text/plain")

    for key, value in raw_headers.items():
        if key.lower() == "set-cookie":
            if isinstance(value, list):
                for cookie_value in value:
                    response.headers.append("set-cookie", cookie_value)
            else:
                for cookie_value in str(value).split("\n"):
                    if cookie_value.strip():
                        response.headers.append("set-cookie", cookie_value.strip())
        else:
            response.headers[key] = str(value)

    return response


def rewrite_html_paths(html: str, target: str) -> str:
    """Rewrite relative paths inside HTML to stay under /proxy/<target> prefix."""
    prefix = f"/proxy/{target}"

    def rewrite_url(raw: str) -> str:
        if not raw or raw.startswith("#") or raw.startswith("?"):
            return raw
        if raw.startswith(("http://", "https://", "//", "mailto:", "tel:")):
            return raw
        if raw.startswith("/"):
            return f"{prefix}{raw}"
        return f"{prefix}/{raw.lstrip('./')}"

    def replace_attr(match: re.Match[str]) -> str:
        attr, quote, value = match.group(1), match.group(2), match.group(3)
        rewritten = rewrite_url(value)
        return f"{attr}={quote}{rewritten}{quote}"

    # href, src, action handles double and single quotes
    attr_pattern = re.compile(r'(href|src|action)=(["\'])([^"\']+)\2', flags=re.IGNORECASE)
    html = attr_pattern.sub(replace_attr, html)

    # CSS url() references
    url_pattern = re.compile(r'url\(\s*(["\']?)([^"\')]+)\1\s*\)', flags=re.IGNORECASE)

    def replace_url(match: re.Match[str]) -> str:
        quote, value = match.group(1), match.group(2)
        rewritten = rewrite_url(value)
        return f"url({quote}{rewritten}{quote})"

    return url_pattern.sub(replace_url, html)


@router.api_route("/proxy/{target}/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
@router.api_route("/proxy/{target}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def proxy_endpoint(request: Request, target: str, path: str = "") -> Response:
    """Public proxy endpoint entrypoint: validates services and forwards to ProxyService."""
    service: ProxyService = request.app.state.proxy_service
    return await service.process_request(request, target=target, path=path)
