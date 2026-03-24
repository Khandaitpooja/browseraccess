from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional

from pydantic import BaseModel, Field


class AgentRegistration(BaseModel):
    agent_id: str = Field(..., min_length=3, max_length=128)
    token: str = Field(..., min_length=8, max_length=512)


class ProxyRequestMessage(BaseModel):
    id: str
    method: str
    target: str
    path: str
    query: str = ""
    headers: Dict[str, str] = Field(default_factory=dict)
    body: Optional[str] = None
    timeout_seconds: float = 20.0


class ProxyResponseMessage(BaseModel):
    id: str
    status: int
    headers: Dict[str, str] = Field(default_factory=dict)
    body: str = ""
    error: Optional[str] = None


class HealthMessage(BaseModel):
    type: str = "health"
    at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
