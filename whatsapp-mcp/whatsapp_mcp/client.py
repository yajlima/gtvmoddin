"""Minimal WhatsApp Business Cloud API client (Meta Graph API), stdlib only."""

from __future__ import annotations

import json
import mimetypes
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .config import Config


class WhatsAppError(Exception):
    pass


class WhatsAppClient:
    def __init__(self, config: Config, timeout: float = 30.0):
        self.config = config
        self.timeout = timeout

    # -- plumbing ---------------------------------------------------------

    def _require(self, *names: str) -> None:
        missing = [n for n in names if not getattr(self.config, n)]
        if missing:
            env = ", ".join("WHATSAPP_" + n.upper() for n in missing)
            raise WhatsAppError(f"not configured: set {env}")

    def _url(self, path: str) -> str:
        return f"{self.config.graph_url}/{self.config.api_version}/{path.lstrip('/')}"

    def _request(self, method: str, url: str, body: dict | None = None, raw: bool = False):
        self._require("access_token")
        headers = {"Authorization": f"Bearer {self.config.access_token}"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = resp.read()
                if raw:
                    return payload, resp.headers.get("Content-Type", "")
                return json.loads(payload or b"{}")
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")
            try:
                err = json.loads(detail)["error"]
                detail = f"{err.get('message')} (code {err.get('code')})"
            except (ValueError, KeyError, TypeError):
                pass
            raise WhatsAppError(f"Graph API {e.code}: {detail}") from None
        except urllib.error.URLError as e:
            raise WhatsAppError(f"network error: {e.reason}") from None

    def _send(self, to: str, type_: str, payload: dict, reply_to: str | None = None) -> dict:
        self._require("access_token", "phone_number_id")
        body = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": type_,
            type_: payload,
        }
        if reply_to:
            body["context"] = {"message_id": reply_to}
        return self._request("POST", self._url(f"{self.config.phone_number_id}/messages"), body)

    # -- messages ---------------------------------------------------------

    def send_text(self, to: str, text: str, preview_url: bool = False, reply_to: str | None = None) -> dict:
        return self._send(to, "text", {"body": text, "preview_url": preview_url}, reply_to)

    def send_media(self, to: str, kind: str, link: str | None = None, media_id: str | None = None,
                   caption: str | None = None, filename: str | None = None,
                   reply_to: str | None = None) -> dict:
        if kind not in ("image", "video", "audio", "document", "sticker"):
            raise WhatsAppError(f"unsupported media type: {kind}")
        if bool(link) == bool(media_id):
            raise WhatsAppError("pass exactly one of link or media_id")
        payload: dict = {"link": link} if link else {"id": media_id}
        if caption and kind in ("image", "video", "document"):
            payload["caption"] = caption
        if filename and kind == "document":
            payload["filename"] = filename
        return self._send(to, kind, payload, reply_to)

    def send_template(self, to: str, name: str, language: str = "en_US",
                      components: list | None = None) -> dict:
        payload: dict = {"name": name, "language": {"code": language}}
        if components:
            payload["components"] = components
        return self._send(to, "template", payload)

    def send_reaction(self, to: str, message_id: str, emoji: str) -> dict:
        return self._send(to, "reaction", {"message_id": message_id, "emoji": emoji})

    def send_location(self, to: str, latitude: float, longitude: float,
                      name: str | None = None, address: str | None = None) -> dict:
        payload: dict = {"latitude": latitude, "longitude": longitude}
        if name:
            payload["name"] = name
        if address:
            payload["address"] = address
        return self._send(to, "location", payload)

    def mark_read(self, message_id: str) -> dict:
        self._require("phone_number_id")
        body = {"messaging_product": "whatsapp", "status": "read", "message_id": message_id}
        return self._request("POST", self._url(f"{self.config.phone_number_id}/messages"), body)

    # -- media ------------------------------------------------------------

    def download_media(self, media_id: str, dest_dir: Path) -> Path:
        meta = self._request("GET", self._url(media_id))
        url = meta.get("url")
        if not url:
            raise WhatsAppError(f"no download url for media {media_id}")
        data, ctype = self._request("GET", url, raw=True)
        mime = meta.get("mime_type") or ctype.split(";")[0]
        ext = mimetypes.guess_extension(mime or "") or ".bin"
        dest_dir.mkdir(parents=True, exist_ok=True)
        path = dest_dir / (re.sub(r"[^\w.-]", "_", media_id) + ext)
        path.write_bytes(data)
        return path

    # -- account ----------------------------------------------------------

    def list_templates(self, limit: int = 50) -> list[dict]:
        self._require("business_account_id")
        q = urllib.parse.urlencode({"limit": limit, "fields": "name,language,status,category,components"})
        resp = self._request("GET", self._url(f"{self.config.business_account_id}/message_templates?{q}"))
        return resp.get("data", [])

    def phone_number_info(self) -> dict:
        self._require("phone_number_id")
        q = urllib.parse.urlencode({"fields": "display_phone_number,verified_name,quality_rating"})
        return self._request("GET", self._url(f"{self.config.phone_number_id}?{q}"))
