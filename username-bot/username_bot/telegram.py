"""Tiny Telegram Bot API client (stdlib only)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request


class TelegramError(Exception):
    pass


class Telegram:
    def __init__(self, token: str, api: str = "https://api.telegram.org"):
        if not token:
            raise TelegramError("set TELEGRAM_BOT_TOKEN")
        self.base = f"{api.rstrip('/')}/bot{token}"
        self.file_base = f"{api.rstrip('/')}/file/bot{token}"

    def call(self, method: str, http_timeout: float = 30, **params):
        body = json.dumps({k: v for k, v in params.items() if v is not None}).encode()
        req = urllib.request.Request(f"{self.base}/{method}", data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=http_timeout) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            raw = e.read()
        except urllib.error.URLError as e:
            raise TelegramError(f"network error: {e.reason}") from None
        try:
            resp = json.loads(raw)
        except ValueError:
            raise TelegramError(f"{method}: unexpected response") from None
        if not resp.get("ok"):
            raise TelegramError(f"{method}: {resp.get('description', 'unknown error')}")
        return resp["result"]

    def send(self, chat_id, text: str, buttons: list[list[tuple[str, str]]] | None = None,
             html: bool = False) -> dict:
        markup = None
        if buttons:
            markup = {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row] for row in buttons]}
        return self.call("sendMessage", chat_id=chat_id, text=text[:4096], reply_markup=markup,
                         parse_mode="HTML" if html else None)

    def updates(self, offset: int | None, timeout: int = 25) -> list[dict]:
        return self.call("getUpdates", http_timeout=timeout + 10, offset=offset, timeout=timeout,
                         allowed_updates=["message", "callback_query"])

    def answer(self, callback_id: str, text: str | None = None) -> None:
        self.call("answerCallbackQuery", callback_query_id=callback_id, text=text)

    def clear_buttons(self, chat_id, message_id: int) -> None:
        try:
            self.call("editMessageReplyMarkup", chat_id=chat_id, message_id=message_id,
                      reply_markup={"inline_keyboard": []})
        except TelegramError:
            pass  # message too old or already edited; not worth failing over

    def download(self, file_id: str, max_bytes: int) -> bytes:
        info = self.call("getFile", file_id=file_id)
        if info.get("file_size", 0) > max_bytes:
            raise TelegramError(f"file too big (max {max_bytes // 1024} KB)")
        try:
            with urllib.request.urlopen(f"{self.file_base}/{info['file_path']}", timeout=60) as r:
                return r.read(max_bytes + 1)[:max_bytes]
        except urllib.error.URLError as e:
            raise TelegramError(f"download failed: {e}") from None
