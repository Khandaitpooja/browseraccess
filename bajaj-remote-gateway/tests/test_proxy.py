"""Tests for proxy functionality, HTML rewriting, and validation."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient
from fastapi import WebSocket

from server.main import create_app
from server.connection_manager import ConnectionManager
from server.ws_manager import PendingRequestManager
from server.proxy_routes import ProxyService, rewrite_html_paths, valid_target
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


@pytest.fixture
def proxy_service(app):
    """ProxyService instance."""
    return ProxyService(
        connections=app.state.connections,
        pending=app.state.pending,
        timeout_seconds=1.0  # Short timeout for tests
    )


@pytest.mark.asyncio
async def test_proxy_flow_success(app, client):
    """Test successful proxy request with mocked agent response."""
    # Register mock agent
    mock_ws = AsyncMock(spec=WebSocket)
    await app.state.connections.register("test-agent", mock_ws)

    # Mock agent response via send_json side effect
    async def send_json_side_effect(message):
        response = ProxyResponseMessage(
            id=message["id"],
            status=200,
            headers={"content-type": "text/plain"},
            body="Hello World"
        )
        await app.state.pending.resolve(response)

    mock_ws.send_json = AsyncMock(side_effect=send_json_side_effect)

    # Make proxy request
    response = client.get("/proxy/192.168.1.1:80/test")
    assert response.status_code == 200
    assert response.text == "Hello World"
    assert response.headers["content-type"] == "text/plain"


@pytest.mark.asyncio
async def test_proxy_flow_timeout(app, client):
    """Test proxy request timeout when agent doesn't respond."""
    # Register mock agent
    mock_ws = AsyncMock(spec=WebSocket)
    await app.state.connections.register("test-agent", mock_ws)

    # Mock websocket send but no response (no side_effect)
    mock_ws.send_json = AsyncMock()

    # Make proxy request
    response = client.get("/proxy/192.168.1.1:80/test")
    assert response.status_code == 504
    assert "timeout" in response.json()["detail"]


def test_html_rewriting_href():
    """Test HTML href rewriting."""
    html = '<a href="/login">Login</a>'
    result = rewrite_html_paths(html, "192.168.1.1:80")
    assert 'href="/proxy/192.168.1.1:80/login"' in result


def test_html_rewriting_src():
    """Test HTML src rewriting."""
    html = '<img src="image.jpg">'
    result = rewrite_html_paths(html, "192.168.1.1:80")
    assert 'src="/proxy/192.168.1.1:80/image.jpg"' in result


def test_html_rewriting_relative():
    """Test HTML relative path rewriting."""
    html = '<link href="styles.css">'
    result = rewrite_html_paths(html, "192.168.1.1:80")
    assert 'href="/proxy/192.168.1.1:80/styles.css"' in result


def test_html_rewriting_absolute():
    """Test HTML absolute URL not rewritten."""
    html = '<a href="https://example.com">External</a>'
    result = rewrite_html_paths(html, "192.168.1.1:80")
    assert 'href="https://example.com"' in result


def test_html_rewriting_css_url():
    """Test CSS url() rewriting."""
    html = 'background: url("bg.jpg");'
    result = rewrite_html_paths(html, "192.168.1.1:80")
    assert 'url("/proxy/192.168.1.1:80/bg.jpg")' in result


def test_valid_target_valid():
    """Test valid target formats."""
    assert valid_target("192.168.1.1:80")
    assert valid_target("example.com:443")
    assert valid_target("localhost:3000")


def test_valid_target_invalid():
    """Test invalid target formats."""
    assert not valid_target("")
    assert not valid_target("192.168.1.1")  # No port
    assert not valid_target("192.168.1.1:99999")  # Invalid port
    assert not valid_target("http://example.com:80")  # Scheme not allowed
    assert not valid_target("192.168.1.1:80/extra")  # Extra path


@pytest.mark.asyncio
async def test_proxy_invalid_target(client):
    """Test proxy route with invalid target returns 400."""
    response = client.get("/proxy/invalid-target/")
    assert response.status_code == 400
    assert "Invalid target format" in response.json()["detail"]