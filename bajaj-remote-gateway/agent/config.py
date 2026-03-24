from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(slots=True)
class AgentConfig:
    agent_id: str
    server_ws_url: str
    token: str
    request_timeout: float
    reconnect_seconds: float


    @classmethod
    def from_env(cls) -> "AgentConfig":
        return cls(
            agent_id=os.getenv("AGENT_ID", "agent-01"),
            server_ws_url=os.getenv("SERVER_WS_URL", "ws://127.0.0.1:8000/ws/agent"),
            token=os.getenv("AGENT_TOKEN", "change-me"),
            request_timeout=float(os.getenv("REQUEST_TIMEOUT", "20")),
            reconnect_seconds=float(os.getenv("RECONNECT_SECONDS", "3")),
        )
