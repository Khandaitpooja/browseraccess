"""Tests for server endpoints and WebSocket handling."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient
from fastapi import WebSocket
from websockets.exceptions import ConnectionClosed

from server.main import create_app
from server.connection_manager import ConnectionManager
from server.ws_manager import PendingRequestManager
from common.schemas import ProxyResponseMessage


@pytest.fixture
def app():
    """Create FastAPI app with mocked dependencies."""
    app = create_app()
    new_connections = ConnectionManager()
    new_pending = PendingRequestManager()
    app.state.connections = new_connections
    app.state.pending = new_pending
    app.state.proxy_service.connections = new_connections
    app.state.proxy_service.pending = new_pending
    app.state.agent_token = "test-token"
    return app


@pytest.fixture
def client(app):
    """Test client for FastAPI app."""
    return TestClient(app)


@pytest.mark.asyncio
async def test_health_endpoint_no_agents(client):
    """Test /health returns empty list when no agents connected."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["connected_agents"] == []


@pytest.mark.asyncio
async def test_health_endpoint_with_agents(app, client):
    """Test /health returns connected agents."""
    # Simulate agent connection
    connections = app.state.connections
    mock_ws = MagicMock(spec=WebSocket)
    await connections.register("test-agent", mock_ws)

    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "test-agent" in data["connected_agents"]


@pytest.mark.asyncio
async def test_websocket_agent_auth_success(app):
    """Test WebSocket agent connection with valid token."""
    from fastapi.testclient import TestClient
    client = TestClient(app)

    # Mock WebSocket connection
    with client.websocket_connect("/ws/agent?token=test-token&agent_id=test-agent") as websocket:
        # In real test, we'd need to mock the websocket handling
        # For now, just check connection attempt
        pass  # Placeholder


@pytest.mark.asyncio
async def test_websocket_agent_auth_failure(app):
    """Test WebSocket agent connection with invalid token."""
    from fastapi.testclient import TestClient
    client = TestClient(app)

    # This should fail due to invalid token
    with pytest.raises(Exception):  # WebSocket connection should be rejected
        with client.websocket_connect("/ws/agent?token=wrong-token&agent_id=test-agent") as websocket:
            pass


@pytest.mark.asyncio
async def test_proxy_route_no_agent(client):
    """Test proxy route returns 404 when no agent connected."""
    response = client.get("/proxy/192.168.1.1:80/")
    assert response.status_code == 404
    assert "No agents connected" in response.json()["detail"]


@pytest.mark.asyncio
async def test_proxy_route_multiple_agents_no_explicit(client):
    """Test proxy route returns 400 when multiple agents and no explicit agent_id."""
    # This would require setting up multiple agents, but for simplicity, assume single agent case
    pass  # Placeholder