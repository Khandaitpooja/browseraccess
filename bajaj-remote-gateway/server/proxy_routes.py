from __future__ import annotations

import asyncio
import base64
import logging
import re
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, Response

from common.schemas import ProxyRequestMessage, ProxyResponseMessage

from .connection_manager import ConnectionManager
from .ws_manager import PendingRequestManager

router = APIRouter(tags=["proxy"])

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


class ProxyService:
    def __init__(self, connections: ConnectionManager, pending: PendingRequestManager, timeout_seconds: float = 20.0):
        self.connections = connections
        self.pending = pending
        self.timeout_seconds = timeout_seconds

    async def process_request(self, request: Request, target: str, path: str) -> Response:
        agent_id = await self._resolve_agent_id(request)
        agent = await self.connections.get(agent_id)
        if not agent:
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

        future = await self.pending.create(request_id)
        try:
            await agent.websocket.send_json(proxy_message.model_dump())
        except Exception as exc:  # noqa: BLE001
            await self.pending.cleanup(request_id)
            logging.exception("agent_send_failed", extra={"agent_id": agent_id, "request_id": request_id})
            raise HTTPException(status_code=502, detail="Failed to forward request to agent") from exc

        try:
            response_message = await asyncio.wait_for(future, timeout=self.timeout_seconds)
        except TimeoutError as exc:
            await self.pending.fail(request_id, "Agent timeout")
            raise HTTPException(status_code=504, detail="Agent response timeout") from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        if response_message.error:
            raise HTTPException(status_code=502, detail=response_message.error)

        return build_http_response(response_message, target)

    async def _resolve_agent_id(self, request: Request) -> str:
        explicit_agent = request.query_params.get("agent_id")
        if explicit_agent:
            return explicit_agent

        agents = await self.connections.list_agents()
        if len(agents) == 1:
            return agents[0]

        raise HTTPException(
            status_code=400,
            detail="Multiple agents connected. Provide ?agent_id=<agent_id>",
        )


def build_http_response(proxy_response: ProxyResponseMessage, target: str) -> Response:
    content_type = proxy_response.headers.get("content-type", "")
    body_text = proxy_response.body
    if body_text.startswith(BINARY_PREFIX):
        body_bytes = base64.b64decode(body_text[len(BINARY_PREFIX) :])
    else:
        if "text/html" in content_type.lower():
            body_text = rewrite_html_paths(body_text, target)
        body_bytes = body_text.encode("utf-8", errors="ignore")

    headers = {k: v for k, v in proxy_response.headers.items() if k.lower() not in HOP_BY_HOP_HEADERS}

    response = Response(content=body_bytes, status_code=proxy_response.status)

    for key, value in headers.items():
        if key.lower() == "set-cookie":
            for cookie_value in value.split("\n"):
                response.headers.append("set-cookie", cookie_value)
        else:
            response.headers[key] = value

    return response


def rewrite_html_paths(html: str, target: str) -> str:
    prefix = f"/proxy/{target}"

    def _rewrite(match: re.Match[str]) -> str:
        attr = match.group(1)
        path = match.group(2)
        return f'{attr}="{prefix}{path}"'

    pattern = re.compile(r'(href|src)="(/[^\"]*)"', flags=re.IGNORECASE)
    return pattern.sub(_rewrite, html)


@router.api_route("/proxy/{target}/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"])
@router.api_route("/proxy/{target}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"])
async def proxy_endpoint(request: Request, target: str, path: str = "") -> Response:
    service: ProxyService = request.app.state.proxy_service
    return await service.process_request(request, target=target, path=path)
