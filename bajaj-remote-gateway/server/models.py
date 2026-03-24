from __future__ import annotations

from dataclasses import dataclass

from fastapi import WebSocket


@dataclass(slots=True)
class AgentConnection:
    agent_id: str
    websocket: WebSocket
