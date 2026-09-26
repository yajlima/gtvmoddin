import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import anyio
import pytest

from notify_mcp.channels import CallMeBot, Config, NotifyError, Telegram

ROOT = Path(__file__).resolve().parents[1]
CHAT = 4242


class FakeServices:
    """Fake Telegram Bot API plus a fake CallMeBot endpoint."""

    def __init__(self):
        self.sent = []          # sendMessage payloads
        self.calls = []         # CallMeBot query dicts
        self.updates = []       # pending updates
        self.next_update = 1
        self.next_msg = 100
        self.on_send = None     # hook(payload, message_id)
        self.call_reply = "Call to @me queued. Calling..."
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body: bytes, ctype="application/json"):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                u = urlparse(self.path)
                fake.calls.append({k: v[0] for k, v in parse_qs(u.query).items()})
                page = f"<html><script>gtag('x')</script><body><p>{fake.call_reply}</p></body></html>"
                self._send(200, page.encode(), "text/html")

            def do_POST(self):
                _, token, method = self.path.split("/", 2)
                params = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
                if token != "botTOKEN":
                    return self._send(401, b'{"ok":false,"description":"Unauthorized"}')
                result = fake.handle(method, params)
                self._send(200, json.dumps({"ok": True, "result": result}).encode())

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def push(self, update: dict):
        update["update_id"] = self.next_update
        self.next_update += 1
        self.updates.append(update)

    def text_from(self, chat_id, text):
        self.push({"message": {"message_id": 1, "chat": {"id": chat_id, "first_name": "Sam", "username": "sam"},
                               "text": text}})

    def handle(self, method, p):
        if method == "getMe":
            return {"id": 1, "is_bot": True, "username": "my_agent_bot"}
        if method == "sendMessage":
            self.next_msg += 1
            self.sent.append(p)
            if self.on_send:
                self.on_send(p, self.next_msg)
            return {"message_id": self.next_msg, "chat": {"id": int(p["chat_id"])}}
        if method == "answerCallbackQuery":
            return True
        if method == "getUpdates":
            offset = p.get("offset")
            if offset == -1:
                return self.updates[-1:]
            if offset:
                self.updates = [u for u in self.updates if u["update_id"] >= offset]
            deadline = time.monotonic() + min(p.get("timeout", 0), 2)
            while not self.updates and time.monotonic() < deadline:
                time.sleep(0.05)
            return list(self.updates)
        raise AssertionError(method)

    def close(self):
        self.httpd.shutdown()


@pytest.fixture
def fake():
    f = FakeServices()
    yield f
    f.close()


@pytest.fixture
def config(fake):
    return Config(bot_token="TOKEN", chat_id=str(CHAT), call_user="@me",
                  telegram_api=fake.url, callmebot_url=fake.url + "/start.php")


def test_send_and_silent(fake, config):
    tg = Telegram(config)
    tg.send("hello")
    tg.send("psst", silent=True)
    assert fake.sent[0] == {"chat_id": str(CHAT), "text": "hello"}
    assert fake.sent[1]["disable_notification"] is True


def test_missing_config():
    with pytest.raises(NotifyError, match="TELEGRAM_BOT_TOKEN"):
        Telegram(Config()).send("x")
    with pytest.raises(NotifyError, match="TELEGRAM_CHAT_ID"):
        Telegram(Config(bot_token="t")).send("x")
    with pytest.raises(NotifyError, match="TELEGRAM_USERNAME"):
        CallMeBot(Config()).call("x")


def test_bad_token_surfaces_telegram_error(fake, config):
    config.bot_token = "WRONG"
    with pytest.raises(NotifyError, match="Unauthorized"):
        Telegram(config).send("x")


def test_ask_button_answer(fake, config):
    def tap(payload, msg_id):
        if "reply_markup" in payload:
            fake.push({"callback_query": {"id": "cb1", "data": "1",
                                          "message": {"message_id": msg_id, "chat": {"id": CHAT}}}})

    fake.on_send = tap
    result = Telegram(config).ask("deploy?", ["yes", "no"], timeout_s=5)
    assert result == {"answered": True, "answer": "no", "via": "button"}
    buttons = fake.sent[0]["reply_markup"]["inline_keyboard"]
    assert [b[0]["text"] for b in buttons] == ["yes", "no"]
    assert fake.sent[-1]["text"] == "✅ no"


def test_ask_ignores_old_and_foreign_messages(fake, config):
    fake.text_from(CHAT, "old message from before the question")

    def reply(payload, msg_id):
        if payload["text"] == "which branch?":
            fake.text_from(999, "stranger trying to answer")
            fake.text_from(CHAT, "main")

    fake.on_send = reply
    assert Telegram(config).ask("which branch?", None, timeout_s=5) == {
        "answered": True, "answer": "main", "via": "text"}


def test_ask_times_out(fake, config):
    start = time.monotonic()
    assert Telegram(config).ask("hello?", None, timeout_s=1) == {"answered": False, "timed_out": True}
    assert time.monotonic() - start < 5


def test_call(fake, config):
    status = CallMeBot(config).call("x" * 300, repeat=9)
    q = fake.calls[-1]
    assert q["user"] == "@me" and len(q["text"]) == 256 and q["rpt"] == "5" and q["cc"] == "missed"
    assert "gtag" not in status and "Calling" in status


def test_call_unauthorized(fake, config):
    fake.call_reply = "Authorization for user @me is not received. Warning! User not authorized."
    with pytest.raises(NotifyError, match="not authorized"):
        CallMeBot(config).call("hi")


def test_setup_cli(fake, config):
    env = dict(os.environ, TELEGRAM_BOT_TOKEN="TOKEN", TELEGRAM_API_URL=fake.url, PYTHONPATH=str(ROOT))
    out = subprocess.run([sys.executable, "-m", "notify_mcp", "setup"], env=env, capture_output=True, text=True)
    assert out.returncode == 1 and "t.me/my_agent_bot" in out.stdout
    fake.text_from(CHAT, "hi")
    out = subprocess.run([sys.executable, "-m", "notify_mcp", "setup"], env=env, capture_output=True, text=True)
    assert out.returncode == 0 and f"TELEGRAM_CHAT_ID={CHAT}" in out.stdout and "@sam" in out.stdout


def test_mcp_end_to_end(fake, config):
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    env = dict(os.environ, TELEGRAM_BOT_TOKEN="TOKEN", TELEGRAM_CHAT_ID=str(CHAT), TELEGRAM_USERNAME="@me",
               TELEGRAM_API_URL=fake.url, CALLMEBOT_URL=fake.url + "/start.php", PYTHONPATH=str(ROOT))
    params = StdioServerParameters(command=sys.executable, args=["-m", "notify_mcp"], env=env)

    def is_error(r):
        return getattr(r, "is_error", None) or getattr(r, "isError", False)

    def payload(r):
        assert not is_error(r), r.content
        return json.loads(r.content[0].text)

    async def run():
        async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            assert {t.name for t in (await s.list_tools()).tools} == {"notify_me", "call_me", "ask_me"}

            assert payload(await s.call_tool("notify_me", {"message": "build done", "urgency": "low"}))["sent"]
            assert fake.sent[-1]["disable_notification"] is True

            urgent = payload(await s.call_tool("notify_me", {"message": "prod is down", "urgency": "urgent"}))
            assert urgent["sent"] and "Calling" in urgent["call"]
            assert fake.calls[-1]["cc"] == "no"  # text already sent, don't duplicate

            fake.call_reply = "User not authorized."
            partial = payload(await s.call_tool("notify_me", {"message": "again", "urgency": "urgent"}))
            assert partial["sent"] and "not authorized" in partial["call_error"]

            bad = await s.call_tool("notify_me", {"message": "x", "urgency": "mega"})
            assert is_error(bad) and "urgency" in bad.content[0].text

            fake.on_send = lambda p, mid: fake.text_from(CHAT, "ship it") if p["text"] == "ok to deploy?" else None
            answer = payload(await s.call_tool("ask_me", {"question": "ok to deploy?", "timeout_seconds": 10}))
            assert answer == {"answered": True, "answer": "ship it", "via": "text"}

    anyio.run(run)
