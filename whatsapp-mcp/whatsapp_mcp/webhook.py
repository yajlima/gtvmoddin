"""Webhook receiver for inbound WhatsApp messages and delivery statuses.

Meta calls GET once to verify the endpoint (hub.challenge) and then POSTs
events signed with X-Hub-Signature-256 = HMAC-SHA256(app_secret, body).
Unsigned or badly signed POSTs are rejected.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .config import Config
from .store import Store

log = logging.getLogger("whatsapp_mcp.webhook")

MAX_BODY = 1 << 20  # 1 MiB; real payloads are a few KB


def verify_signature(app_secret: str, body: bytes, header: str | None) -> bool:
    if not app_secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header[len("sha256="):])


def _text_of(msg: dict) -> tuple[str | None, str | None]:
    """Return (text, media_id) summarizing any message type."""
    t = msg.get("type")
    body = msg.get(t) if isinstance(msg.get(t), dict) else {}
    if t == "text":
        return body.get("body"), None
    if t in ("image", "video", "document", "audio", "sticker"):
        return body.get("caption") or body.get("filename"), body.get("id")
    if t == "reaction":
        return body.get("emoji"), None
    if t == "button":
        return body.get("text"), None
    if t == "interactive":
        reply = body.get("button_reply") or body.get("list_reply") or {}
        return reply.get("title"), None
    if t == "location":
        parts = [f"{body.get('latitude')},{body.get('longitude')}", body.get("name"), body.get("address")]
        return " ".join(p for p in parts if p), None
    if t == "contacts":
        names = [c.get("name", {}).get("formatted_name", "") for c in msg.get("contacts", [])]
        return "shared contacts: " + ", ".join(n for n in names if n), None
    return None, None


def ingest(store: Store, payload: dict) -> int:
    """Store every message and status in a webhook payload. Returns count stored."""
    count = 0
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            names = {c.get("wa_id"): c.get("profile", {}).get("name") for c in value.get("contacts", [])}
            for msg in value.get("messages", []):
                text, media_id = _text_of(msg)
                reply_to = (msg.get("context") or {}).get("id")
                if msg.get("type") == "reaction":
                    reply_to = msg.get("reaction", {}).get("message_id")
                store.add(
                    id=msg["id"], direction="in", wa_id=msg["from"], name=names.get(msg["from"]),
                    type=msg.get("type", "unknown"), text=text, media_id=media_id,
                    reply_to=reply_to, timestamp=int(msg.get("timestamp", 0)) or None, raw=msg,
                )
                count += 1
            for st in value.get("statuses", []):
                store.set_status(st["id"], st.get("status", ""))
                count += 1
    return count


def make_handler(config: Config, store: Store):
    class Handler(BaseHTTPRequestHandler):
        server_version = "whatsapp-mcp"

        def log_message(self, fmt, *args):  # route to logging (stdout is the MCP stream)
            log.debug("%s - " + fmt, self.address_string(), *args)

        def _reply(self, code: int, body: bytes = b"", ctype: str = "text/plain") -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            q = parse_qs(urlparse(self.path).query)
            mode = q.get("hub.mode", [""])[0]
            token = q.get("hub.verify_token", [""])[0]
            challenge = q.get("hub.challenge", [""])[0]
            if (mode == "subscribe" and config.verify_token
                    and hmac.compare_digest(token, config.verify_token)):
                self._reply(200, challenge.encode())
            else:
                self._reply(403, b"forbidden")

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY:
                return self._reply(413 if length > MAX_BODY else 400, b"bad length")
            body = self.rfile.read(length)
            if not verify_signature(config.app_secret, body, self.headers.get("X-Hub-Signature-256")):
                log.warning("rejected webhook POST with missing/invalid signature")
                return self._reply(403, b"bad signature")
            try:
                n = ingest(store, json.loads(body))
            except (ValueError, KeyError, TypeError) as e:
                log.warning("bad webhook payload: %s", e)
                return self._reply(400, b"bad payload")
            log.info("webhook stored %d item(s)", n)
            self._reply(200, b"ok")

    return Handler


def start_webhook(config: Config, store: Store) -> ThreadingHTTPServer:
    """Start the webhook server on a daemon thread and return it."""
    if not config.app_secret:
        log.warning("WHATSAPP_APP_SECRET is not set: every webhook POST will be rejected")
    if not config.verify_token:
        log.warning("WHATSAPP_VERIFY_TOKEN is not set: Meta's endpoint verification will fail")
    httpd = ThreadingHTTPServer((config.webhook_host, config.webhook_port), make_handler(config, store))
    threading.Thread(target=httpd.serve_forever, name="whatsapp-webhook", daemon=True).start()
    log.info("webhook listening on http://%s:%d/", *httpd.server_address[:2])
    return httpd
