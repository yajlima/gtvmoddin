"""Telegram Bot API (texts, questions) and CallMeBot (Telegram voice calls)."""

from __future__ import annotations

import html
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass


class NotifyError(Exception):
    pass


@dataclass
class Config:
    bot_token: str = ""
    chat_id: str = ""
    call_user: str = ""  # Telegram @username (or phone with country code) for CallMeBot
    call_lang: str = ""
    telegram_api: str = "https://api.telegram.org"
    callmebot_url: str = "https://api.callmebot.com/start.php"

    @classmethod
    def from_env(cls) -> "Config":
        env = os.environ.get
        return cls(
            bot_token=env("TELEGRAM_BOT_TOKEN", ""),
            chat_id=env("TELEGRAM_CHAT_ID", ""),
            call_user=env("TELEGRAM_USERNAME", ""),
            call_lang=env("CALLMEBOT_LANG", ""),
            telegram_api=env("TELEGRAM_API_URL", cls.telegram_api).rstrip("/"),
            callmebot_url=env("CALLMEBOT_URL", cls.callmebot_url),
        )


def _http(url: str, data: dict | None = None, timeout: float = 30) -> bytes:
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method="POST" if body else "GET",
                                 headers={"Content-Type": "application/json"} if body else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        return e.read()  # Telegram puts the reason in the JSON body
    except urllib.error.URLError as e:
        raise NotifyError(f"network error: {e.reason}") from None


class Telegram:
    def __init__(self, config: Config):
        self.config = config
        self._offset = 0
        self._poll_lock = threading.Lock()  # getUpdates must not run concurrently

    def _call(self, method: str, http_timeout: float = 30, **params):
        if not self.config.bot_token:
            raise NotifyError("not configured: set TELEGRAM_BOT_TOKEN")
        url = f"{self.config.telegram_api}/bot{self.config.bot_token}/{method}"
        raw = _http(url, {k: v for k, v in params.items() if v is not None}, http_timeout)
        try:
            resp = json.loads(raw)
        except ValueError:
            raise NotifyError(f"Telegram {method}: unexpected response") from None
        if not resp.get("ok"):
            desc = resp.get("description", "unknown error")
            if "conflict" in desc.lower() and "webhook" in desc.lower():
                desc += " (this bot has a webhook set; call deleteWebhook or use a separate bot)"
            raise NotifyError(f"Telegram {method}: {desc}")
        return resp["result"]

    def _chat(self) -> str:
        if not self.config.bot_token:
            raise NotifyError("not configured: set TELEGRAM_BOT_TOKEN")
        if not self.config.chat_id:
            raise NotifyError("not configured: set TELEGRAM_CHAT_ID (run `notify-mcp setup` to find it)")
        return self.config.chat_id

    def send(self, text: str, silent: bool = False, options: list[str] | None = None) -> int:
        markup = None
        if options:
            markup = {"inline_keyboard": [[{"text": o, "callback_data": str(i)}] for i, o in enumerate(options)]}
        msg = self._call("sendMessage", chat_id=self._chat(), text=text[:4096],
                         disable_notification=silent or None, reply_markup=markup)
        return msg["message_id"]

    def updates(self, timeout: int = 0) -> list[dict]:
        ups = self._call("getUpdates", http_timeout=timeout + 10, offset=self._offset or None,
                         timeout=timeout, allowed_updates=["message", "callback_query"])
        if ups:
            self._offset = ups[-1]["update_id"] + 1
        return ups

    def ask(self, question: str, options: list[str] | None, timeout_s: float) -> dict:
        chat = str(self._chat())
        with self._poll_lock:
            # Skip anything sent before the question so old chatter isn't taken as the answer.
            last = self._call("getUpdates", offset=-1, timeout=0)
            if last:
                self._offset = last[-1]["update_id"] + 1
            msg_id = self.send(question, options=options)
            deadline = time.monotonic() + timeout_s
            while (remaining := deadline - time.monotonic()) > 0:
                for up in self.updates(timeout=int(min(25, max(1, remaining)))):
                    cb = up.get("callback_query")
                    if cb and str(cb["message"]["chat"]["id"]) == chat and cb["message"]["message_id"] == msg_id:
                        self._call("answerCallbackQuery", callback_query_id=cb["id"], text="got it")
                        idx = int(cb.get("data", -1))
                        answer = options[idx] if options and 0 <= idx < len(options) else cb.get("data")
                        self.send(f"✅ {answer}", silent=True)
                        return {"answered": True, "answer": answer, "via": "button"}
                    m = up.get("message")
                    if m and str(m["chat"]["id"]) == chat and m.get("text"):
                        return {"answered": True, "answer": m["text"], "via": "text"}
        return {"answered": False, "timed_out": True}


class CallMeBot:
    def __init__(self, config: Config):
        self.config = config

    def call(self, text: str, repeat: int = 2, text_copy: str = "missed") -> str:
        if not self.config.call_user:
            raise NotifyError("not configured: set TELEGRAM_USERNAME (your @username) for calls")
        params = {"user": self.config.call_user, "text": text[:256], "rpt": max(1, min(repeat, 5)),
                  "cc": text_copy}
        if self.config.call_lang:
            params["lang"] = self.config.call_lang
        raw = _http(f"{self.config.callmebot_url}?{urllib.parse.urlencode(params)}", timeout=60)
        # CallMeBot answers with a small HTML page describing what happened.
        page = re.sub(r"<(script|style)\b.*?</\1>", " ", raw.decode(errors="replace"), flags=re.S | re.I)
        page = html.unescape(re.sub(r"<[^>]+>", " ", page))
        summary = re.sub(r"\s+", " ", page).strip()[:300]
        if re.search(r"not (authori[sz]ed|registered)|error|invalid", summary, re.I):
            raise NotifyError(f"CallMeBot: {summary}")
        return summary
