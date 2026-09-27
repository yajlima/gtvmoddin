import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from username_bot.bot import Bot
from username_bot.stock import Stock, StockError, slugify, split_details
from username_bot.telegram import Telegram

ROOT = Path(__file__).resolve().parents[1]
ME = 4242


class FakeTelegram:
    """Just enough of the Bot API over HTTP to drive the bot."""

    def __init__(self):
        self.sent = []      # sendMessage payloads
        self.answers = []
        self.edits = []
        self.files = {}     # file_id -> bytes
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _reply(self, obj, raw: bytes | None = None):
                body = raw if raw is not None else json.dumps({"ok": True, "result": obj}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):  # file downloads
                fid = self.path.rsplit("/", 1)[-1]
                self._reply(None, fake.files[fid])

            def do_POST(self):
                method = self.path.rsplit("/", 1)[-1]
                p = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
                if method == "sendMessage":
                    fake.sent.append(p)
                    return self._reply({"message_id": len(fake.sent), "chat": {"id": int(p["chat_id"])}})
                if method == "answerCallbackQuery":
                    fake.answers.append(p)
                    return self._reply(True)
                if method == "editMessageReplyMarkup":
                    fake.edits.append(p)
                    return self._reply(True)
                if method == "getFile":
                    fid = p["file_id"]
                    return self._reply({"file_id": fid, "file_size": len(fake.files[fid]), "file_path": f"docs/{fid}"})
                if method == "getUpdates":
                    return self._reply([])
                raise AssertionError(method)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def texts(self):
        return [m["text"] for m in self.sent]


@pytest.fixture
def tg():
    f = FakeTelegram()
    yield f
    f.httpd.shutdown()


@pytest.fixture
def bot(tg, tmp_path):
    return Bot(Telegram("TOKEN", tg.url), Stock(tmp_path / "stock"), str(ME), low_stock=1)


def text(t, chat=ME):
    return {"message": {"chat": {"id": chat}, "text": t}}


def tap(data, message_id=1, chat=ME):
    return {"callback_query": {"id": "cb", "data": data, "message": {"message_id": message_id, "chat": {"id": chat}}}}


# -- stock ------------------------------------------------------------------

def test_pick_removes_logs_and_undo_restores(tmp_path):
    s = Stock(tmp_path)
    slug = s.create("English")
    assert slug == "english"
    s.add(slug, "alpha\nbravo\n\n# comment\ncharlie\n")
    picked = {s.pick(slug)["line"] for _ in range(3)}
    assert picked == {"alpha", "bravo", "charlie"}  # every name exactly once
    assert s.listings() == {"english": 0}
    with pytest.raises(StockError, match="out of stock"):
        s.pick(slug)

    s.add(slug, "delta")
    p = s.pick(slug)
    assert (tmp_path / "english.sold.txt").read_text().count("\t") == 8  # 4 entries, 2 tabs each
    assert s.undo(slug, p["id"]) == "delta"
    assert s.listings() == {"english": 1}
    with pytest.raises(StockError):
        s.undo(slug, p["id"])  # can't undo twice


def test_add_skips_duplicates_and_flags_resold(tmp_path):
    s = Stock(tmp_path)
    s.create("nonum")
    s.add("nonum", "Alpha\nbravo")
    s.pick("nonum"), s.pick("nonum")
    r = s.add("nonum", "alpha\nALPHA\ncharlie\ncharlie")
    assert r == {"added": 2, "duplicates": 2, "previously_sold": ["alpha"], "left": 2}


def test_listings_ignore_sold_logs_and_slugify(tmp_path):
    s = Stock(tmp_path)
    s.create("Random Combo!")
    assert s.listings() == {"random-combo": 0}
    with pytest.raises(StockError):
        s.create("random combo")
    with pytest.raises(StockError):
        slugify("!!!")


def test_split_details():
    assert split_details("coolname") == ["coolname"]
    assert split_details("coolname:extra info") == ["coolname", "extra info"]
    assert split_details("a | b") == ["a", "b"]


# -- bot ----------------------------------------------------------------------

def test_new_listing_paste_and_order(tg, bot):
    bot.handle(text("/new english"))
    assert "made <b>english</b>" in tg.texts()[-1]
    bot.handle(text("Steve\nNotch\nsteve"))  # pasted names go into the listing being built
    assert "added 2" in tg.texts()[-1] and "skipped 1" in tg.texts()[-1]
    bot.handle(text("/cancel"))

    bot.handle(text("/menu"))
    buttons = tg.sent[-1]["reply_markup"]["inline_keyboard"]
    assert buttons[0][0] == {"text": "📦 english (2)", "callback_data": "pick:english"}

    n = len(tg.sent)
    bot.handle(tap("pick:english"))
    info, name = tg.sent[n], tg.sent[n + 1]
    assert "english</b> sold · 1 left" in info["text"]
    assert info["reply_markup"]["inline_keyboard"][0][0]["callback_data"].startswith("undo:english:")
    assert name["parse_mode"] == "HTML" and name["text"] in ("<code>Steve</code>", "<code>Notch</code>")
    assert "only 1 left" in tg.sent[n + 2]["text"]  # low stock warning

    bot.handle(tap("pick:english"))
    assert "out of stock" in tg.texts()[-1]
    bot.handle(tap("pick:english"))
    assert "❌" in tg.texts()[-1]


def test_undo_button(tg, bot):
    bot.stock.create("combo")
    bot.stock.add("combo", "x1y2")
    bot.handle(tap("pick:combo"))
    undo_data = next(m for m in tg.sent if "reply_markup" in m and "undo" in json.dumps(m))["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
    bot.handle(tap(undo_data, message_id=7))
    assert "put <code>x1y2</code> back" in tg.texts()[-1]
    assert bot.stock.listings() == {"combo": 1}
    assert tg.edits[-1]["message_id"] == 7  # undo button removed
    bot.handle(tap(undo_data))
    assert "already undone" in tg.answers[-1]["text"]


def test_txt_upload_with_caption_and_while_adding(tg, bot):
    bot.stock.create("english")
    tg.files["f1"] = b"one\r\ntwo\r\n"
    bot.handle({"message": {"chat": {"id": ME}, "caption": "english",
                            "document": {"file_id": "f1", "file_name": "names.txt"}}})
    assert "added 2 to <b>english</b>" in tg.texts()[-1]

    bot.handle(text("/add english"))
    tg.files["f2"] = b"three"
    bot.handle({"message": {"chat": {"id": ME}, "document": {"file_id": "f2", "file_name": "more.TXT"}}})
    assert bot.stock.listings() == {"english": 3}

    tg.files["f3"] = b"x"
    bot.handle({"message": {"chat": {"id": ME}, "caption": "english",
                            "document": {"file_id": "f3", "file_name": "pic.png"}}})
    assert "send a .txt" in tg.texts()[-1]


def test_delete_needs_confirmation(tg, bot):
    bot.stock.create("old")
    bot.handle(text("/delete old"))
    assert tg.sent[-1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "delete:old"
    assert bot.stock.listings() == {"old": 0}
    bot.handle(tap("delete:old"))
    assert bot.stock.listings() == {}


def test_ignores_everyone_else(tg, bot):
    bot.stock.create("english")
    bot.stock.add("english", "secretname")
    bot.handle(text("/menu", chat=999))
    bot.handle(tap("pick:english", chat=999))
    bot.handle({"message": {"chat": {"id": 999}, "caption": "english",
                            "document": {"file_id": "nope", "file_name": "x.txt"}}})
    assert tg.sent == []
    assert bot.stock.listings() == {"english": 1}


def test_unknown_listing_messages(tg, bot):
    bot.handle(text("/add ghost"))
    assert "no listing called <b>ghost</b>" in tg.texts()[-1]
    bot.handle(text("/new"))
    assert "usage" in tg.texts()[-1]


def test_order_cli(tg, tmp_path):
    s = Stock(tmp_path / "stock")
    s.create("nonum")
    s.add("nonum", "abc")
    env = dict(os.environ, TELEGRAM_BOT_TOKEN="TOKEN", TELEGRAM_CHAT_ID=str(ME), TELEGRAM_API_URL=tg.url,
               STOCK_DIR=str(tmp_path / "stock"), PYTHONPATH=str(ROOT))
    run = lambda *a: subprocess.run([sys.executable, "-m", "username_bot", *a], env=env, capture_output=True, text=True)
    out = run("order", "nonum")
    assert out.returncode == 0 and "0 left" in out.stdout
    assert "<code>abc</code>" in tg.texts()
    out = run("order", "nonum")
    assert out.returncode == 1 and "out of stock" in out.stderr
    assert run("stock").stdout == "nonum\t0\n"
