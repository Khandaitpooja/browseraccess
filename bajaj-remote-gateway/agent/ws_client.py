from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlencode, urlparse, urlunparse

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from schemas import ProxyRequestMessage

from config import AgentConfig
from proxy_handler import ProxyHandler


class AgentWebSocketClient:
    """WebSocket client that connects back to public server and forwards requests."""

    def __init__(self, config: AgentConfig, proxy_handler: ProxyHandler) -> None:
        self.config = config
        self.proxy_handler = proxy_handler

    async def run_forever(self) -> None:
        backoff = self.config.reconnect_seconds
        max_backoff = 60

        while True:
            try:
                await self._run_once()
                backoff = self.config.reconnect_seconds
            except Exception:  # noqa: BLE001
                logging.exception("agent_loop_error", extra={"agent_id": self.config.agent_id})
                await asyncio.sleep(backoff)
                backoff = min(max_backoff, backoff * 2)

    async def _run_once(self) -> None:
        ws_url = add_query_params(
            self.config.server_ws_url,
            {"agent_id": self.config.agent_id, "token": self.config.token},
        )

        logging.info("agent_connecting", extra={"ws_url": self.config.server_ws_url, "agent_id": self.config.agent_id})
        async with connect(ws_url, ping_interval=20, ping_timeout=20, max_size=16 * 1024 * 1024) as websocket:
            logging.info("agent_connected", extra={"agent_id": self.config.agent_id})
            sem = asyncio.Semaphore(32)
            tasks: set[asyncio.Task[None]] = set()

            async for raw in websocket:
                data = ProxyRequestMessage.model_validate_json(raw)
                task = asyncio.create_task(self._process_message(data, websocket, sem))
                tasks.add(task)
                task.add_done_callback(tasks.discard)

    async def _process_message(self, msg: ProxyRequestMessage, websocket, sem: asyncio.Semaphore) -> None:  # type: ignore[no-untyped-def]
        async with sem:
            logging.debug("agent_request_received", extra={"agent_id": self.config.agent_id, "request_id": msg.id, "target": msg.target, "path": msg.path})
            response = await self.proxy_handler.handle(msg)
            try:
                await websocket.send(response.model_dump_json())
            except ConnectionClosed:
                logging.warning("agent_send_disconnected", extra={"request_id": msg.id, "agent_id": self.config.agent_id})


def add_query_params(base_url: str, params: dict[str, str]) -> str:
    """Append query string parameters to a websocket URL safely."""
    parsed = urlparse(base_url)
    query = urlencode(params)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, query, parsed.fragment))
