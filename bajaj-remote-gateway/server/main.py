from __future__ import annotations

import logging
import os

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from server.schemas import ProxyResponseMessage

from .connection_manager import ConnectionManager
from .proxy_routes import ProxyService, router as proxy_router
from .ws_manager import PendingRequestManager


def setup_logging() -> None:
    """Initialize module-wide logging format and log level from env."""
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def create_app() -> FastAPI:
    setup_logging()

    app = FastAPI(title="bajaj-remote-gateway-server", version="1.0.0")
    agent_token = os.getenv("AGENT_TOKEN", "change-me")

    connections = ConnectionManager()
    pending = PendingRequestManager()
    proxy_service = ProxyService(connections=connections, pending=pending)

    app.state.connections = connections
    app.state.pending = pending
    app.state.proxy_service = proxy_service
    app.state.agent_token = agent_token

    app.include_router(proxy_router)

    @app.get("/health")
    async def health(request: Request) -> JSONResponse:
        connections = request.app.state.connections
        agents = await connections.list_agents()
        return JSONResponse({"status": "ok", "connected_agents": agents})

    @app.websocket("/ws/agent")
    async def ws_agent(websocket: WebSocket) -> None:
        token = websocket.query_params.get("token", "")
        agent_id = websocket.query_params.get("agent_id", "")

        if token != app.state.agent_token or not valid_agent_id(agent_id):
            await websocket.close(code=1008)
            logging.warning("agent_auth_failed", extra={"agent_id": agent_id})
            return

        await websocket.accept()
        await connections.register(agent_id, websocket)
        logging.info("agent_connected", extra={"agent_id": agent_id})

        try:
            while True:
                payload = await websocket.receive_json()
                response = ProxyResponseMessage.model_validate(payload)
                await pending.resolve(response)
        except WebSocketDisconnect:
            logging.info("agent_disconnected", extra={"agent_id": agent_id})
        except Exception:  # noqa: BLE001
            logging.exception("agent_ws_error", extra={"agent_id": agent_id})
        finally:
            await connections.unregister(agent_id)
            await pending.fail_by_agent(agent_id, "Agent disconnected")

    return app


def valid_agent_id(agent_id: str) -> bool:
    if not agent_id:
        return False
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
    return all(ch in allowed for ch in agent_id)


app = create_app()
