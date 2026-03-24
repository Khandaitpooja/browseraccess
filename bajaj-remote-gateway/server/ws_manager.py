from __future__ import annotations

import asyncio
import logging

from server.schemas import ProxyResponseMessage


class PendingRequestManager:
    """Manage in-flight proxy requests while awaiting agent responses."""

    def __init__(self) -> None:
        self._pending: dict[str, asyncio.Future[ProxyResponseMessage]] = {}
        self._owners: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def create(self, request_id: str, agent_id: str) -> asyncio.Future[ProxyResponseMessage]:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[ProxyResponseMessage] = loop.create_future()
        async with self._lock:
            self._pending[request_id] = future
            self._owners[request_id] = agent_id
        return future

    async def resolve(self, response: ProxyResponseMessage) -> None:
        async with self._lock:
            future = self._pending.pop(response.id, None)
            self._owners.pop(response.id, None)
        if future is None:
            logging.warning("orphan_response", extra={"request_id": response.id})
            return
        if not future.done():
            future.set_result(response)

    async def fail(self, request_id: str, reason: str) -> None:
        async with self._lock:
            future = self._pending.pop(request_id, None)
            self._owners.pop(request_id, None)
        if future and not future.done():
            future.set_exception(RuntimeError(reason))

    async def fail_by_agent(self, agent_id: str, reason: str) -> None:
        async with self._lock:
            orphan_ids = [req_id for req_id, owner in self._owners.items() if owner == agent_id]
            for req_id in orphan_ids:
                future = self._pending.pop(req_id, None)
                self._owners.pop(req_id, None)
                if future and not future.done():
                    future.set_exception(RuntimeError(reason))

    async def cleanup(self, request_id: str) -> None:
        async with self._lock:
            self._pending.pop(request_id, None)
            self._owners.pop(request_id, None)
