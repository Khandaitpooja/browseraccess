from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import Callable

from fastapi import WebSocket

from .models import AgentConnection


class ConnectionManager:
    def __init__(self) -> None:
        self._agents: dict[str, AgentConnection] = {}
        self._lock = asyncio.Lock()

    async def register(self, agent_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            self._agents[agent_id] = AgentConnection(agent_id=agent_id, websocket=websocket)

    async def unregister(self, agent_id: str) -> None:
        async with self._lock:
            self._agents.pop(agent_id, None)

    async def get(self, agent_id: str) -> AgentConnection | None:
        async with self._lock:
            return self._agents.get(agent_id)

    async def broadcast_health(self, sender: Callable[[WebSocket], Awaitable[None]]) -> None:
        async with self._lock:
            websockets = [conn.websocket for conn in self._agents.values()]
        await asyncio.gather(*(sender(ws) for ws in websockets), return_exceptions=True)

    async def list_agents(self) -> list[str]:
        async with self._lock:
            return list(self._agents.keys())
