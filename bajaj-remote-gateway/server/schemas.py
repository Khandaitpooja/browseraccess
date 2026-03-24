"""Shared data models used by both server and agent sides."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class AgentRegistration(BaseModel):
    """Model for agent registration values exchanged during websocket auth."""

    agent_id: str = Field(..., min_length=3, max_length=128)
    token: str = Field(..., min_length=8, max_length=512)


class ProxyRequestMessage(BaseModel):
    """RPC payload that server sends to agent for forwarding an HTTP request."""

    id: str
    method: str
    target: str
    path: str
    query: str = ""
    headers: Dict[str, str] = Field(default_factory=dict)
    body: Optional[str] = None
    timeout_seconds: float = 20.0


class ProxyResponseMessage(BaseModel):
    """RPC payload that agent sends to server with proxied response details."""

    id: str
    status: int
    headers: Dict[str, Any] = Field(default_factory=dict)
    body: str = ""
    error: Optional[str] = None


class HealthMessage(BaseModel):
    type: str = "health"
    at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
