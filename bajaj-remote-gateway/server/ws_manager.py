from __future__ import annotations

import asyncio
import logging

from common.schemas import ProxyResponseMessage


class PendingRequestManager:
    def __init__(self) -> None:
        self._pending: dict[str, asyncio.Future[ProxyResponseMessage]] = {}
        self._lock = asyncio.Lock()

    async def create(self, request_id: str) -> asyncio.Future[ProxyResponseMessage]:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[ProxyResponseMessage] = loop.create_future()
        async with self._lock:
            self._pending[request_id] = future
        return future

    async def resolve(self, response: ProxyResponseMessage) -> None:
        async with self._lock:
            future = self._pending.pop(response.id, None)
        if future is None:
            logging.warning("orphan_response", extra={"request_id": response.id})
            return
        if not future.done():
            future.set_result(response)

    async def fail(self, request_id: str, reason: str) -> None:
        async with self._lock:
            future = self._pending.pop(request_id, None)
        if future and not future.done():
            future.set_exception(RuntimeError(reason))

    async def cleanup(self, request_id: str) -> None:
        async with self._lock:
            self._pending.pop(request_id, None)
