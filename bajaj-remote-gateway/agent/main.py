from __future__ import annotations

import asyncio
import logging
import os

from .config import AgentConfig
from .proxy_handler import ProxyHandler
from .ws_client import AgentWebSocketClient


def setup_logging() -> None:
    """Configure root logger level and basic text format."""
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


async def main() -> None:
    setup_logging()
    config = AgentConfig.from_env()
    handler = ProxyHandler(timeout_seconds=config.request_timeout)
    ws_client = AgentWebSocketClient(config=config, proxy_handler=handler)
    await ws_client.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
