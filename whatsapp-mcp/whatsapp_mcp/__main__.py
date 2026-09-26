"""Entry point: `python -m whatsapp_mcp` (or the `whatsapp-mcp` script)."""

from __future__ import annotations

import logging
import sys

from .config import Config
from .server import create_server
from .store import Store
from .webhook import start_webhook


def main() -> None:
    # stdout carries the MCP protocol, so logs must go to stderr.
    logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    config = Config.from_env()
    store = Store(config.db_path)
    if config.webhook_port:
        start_webhook(config, store)
    create_server(config, store).run("stdio")


if __name__ == "__main__":
    main()
