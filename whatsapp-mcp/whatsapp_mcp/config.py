"""Settings loaded from environment variables."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path


def _digits(number: str) -> str:
    """Normalize a phone number to the digits-only form WhatsApp uses (wa_id)."""
    return re.sub(r"\D", "", number)


@dataclass
class Config:
    access_token: str = ""
    phone_number_id: str = ""
    business_account_id: str = ""
    api_version: str = "v23.0"
    graph_url: str = "https://graph.facebook.com"
    app_secret: str = ""
    verify_token: str = ""
    webhook_host: str = "127.0.0.1"
    webhook_port: int = 0
    db_path: Path = Path("~/.whatsapp-mcp/messages.db")
    media_dir: Path = Path("~/.whatsapp-mcp/media")
    allowed_recipients: set[str] = field(default_factory=set)

    @classmethod
    def from_env(cls) -> "Config":
        env = os.environ.get
        allowed = {_digits(n) for n in env("WHATSAPP_ALLOWED_RECIPIENTS", "").split(",") if _digits(n)}
        return cls(
            access_token=env("WHATSAPP_ACCESS_TOKEN", ""),
            phone_number_id=env("WHATSAPP_PHONE_NUMBER_ID", ""),
            business_account_id=env("WHATSAPP_BUSINESS_ACCOUNT_ID", ""),
            api_version=env("WHATSAPP_API_VERSION", cls.api_version),
            graph_url=env("WHATSAPP_GRAPH_URL", cls.graph_url).rstrip("/"),
            app_secret=env("WHATSAPP_APP_SECRET", ""),
            verify_token=env("WHATSAPP_VERIFY_TOKEN", ""),
            webhook_host=env("WHATSAPP_WEBHOOK_HOST", cls.webhook_host),
            webhook_port=int(env("WHATSAPP_WEBHOOK_PORT", "0") or 0),
            db_path=Path(env("WHATSAPP_DB_PATH", str(cls.db_path))).expanduser(),
            media_dir=Path(env("WHATSAPP_MEDIA_DIR", str(cls.media_dir))).expanduser(),
            allowed_recipients=allowed,
        )

    def check_recipient(self, to: str) -> str:
        """Return the normalized number, or raise if it's not allowed."""
        wa_id = _digits(to)
        if not wa_id:
            raise ValueError(f"invalid phone number: {to!r}")
        if self.allowed_recipients and wa_id not in self.allowed_recipients:
            raise PermissionError(
                f"{wa_id} is not in WHATSAPP_ALLOWED_RECIPIENTS; refusing to send"
            )
        return wa_id
