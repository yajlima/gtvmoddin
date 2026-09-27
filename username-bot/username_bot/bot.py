"""The bot: listing buttons, random username picks, and stock management."""

from __future__ import annotations

import html
import logging
import time

from .stock import Stock, StockError, slugify, split_details
from .telegram import Telegram, TelegramError

log = logging.getLogger("username_bot")

MAX_UPLOAD = 1 << 20  # 1 MiB of usernames is plenty

HELP = """\
<b>username bot</b>
When a listing sells, /get it and I'll send you a random username from it
(and delete that name from the list).

/get <i>name</i> - grab a username, e.g. /get english
/menu - buttons for every listing
/stock - how many names are left
/new <i>name</i> - make a listing, then send names or a .txt
/add <i>name</i> - add names to a listing (paste them or send a .txt)
/delete <i>name</i> - delete a listing
/cancel - stop adding names

Quickest way to make or restock a listing: send a .txt with the listing
name as the caption. A new name makes a new listing."""


class Bot:
    def __init__(self, tg: Telegram, stock: Stock, chat_id: str, low_stock: int = 3):
        self.tg = tg
        self.stock = stock
        self.chat_id = str(chat_id)
        self.low_stock = low_stock
        self.adding: str | None = None  # listing that pasted names/files go into

    def say(self, text: str, buttons=None, html_: bool = True) -> dict:
        return self.tg.send(self.chat_id, text, buttons, html=html_)

    # -- orders ---------------------------------------------------------------

    def order(self, slug: str) -> dict:
        """Pick a username for a sold listing and send it: info first, then each
        detail of the line as its own message so it's easy to copy."""
        try:
            pick = self.stock.pick(slug)
        except StockError as e:
            self.say(f"❌ {html.escape(str(e))}")
            raise
        self.say(f"🛒 <b>{html.escape(slug)}</b> sold · {pick['left']} left",
                 [[("↩️ undo (order cancelled)", f"undo:{slug}:{pick['id']}")]])
        for part in split_details(pick["line"]):
            self.say(f"<code>{html.escape(part)}</code>")
        if pick["left"] == 0:
            self.say(f"🚫 <b>{html.escape(slug)}</b> is out of stock. pause the listing or /add more")
        elif pick["left"] <= self.low_stock:
            self.say(f"⚠️ only {pick['left']} left in <b>{html.escape(slug)}</b>")
        return pick

    def menu(self) -> None:
        listings = self.stock.listings()
        if not listings:
            self.say("no listings yet. make one with /new <i>name</i>")
            return
        rows = [[(f"{'📦' if n else '🚫'} {slug} ({n})", f"pick:{slug}")] for slug, n in listings.items()]
        rows.append([("🔄 refresh", "menu")])
        self.say("which listing sold? tap it and I'll grab a username:", rows)

    # -- updates --------------------------------------------------------------

    def handle(self, update: dict) -> None:
        try:
            if "callback_query" in update:
                self._callback(update["callback_query"])
            elif "message" in update:
                self._message(update["message"])
        except (StockError, TelegramError) as e:
            log.info("handled error: %s", e)
        except Exception:
            log.exception("error handling update")
            try:
                self.say("💥 something broke handling that, check the bot logs")
            except TelegramError:
                pass

    def _mine(self, chat: dict) -> bool:
        return str(chat.get("id")) == self.chat_id

    def _callback(self, cb: dict) -> None:
        msg = cb.get("message") or {}
        if not self._mine(msg.get("chat", {})):
            return self.tg.answer(cb["id"])
        action, _, arg = cb.get("data", "").partition(":")
        if action == "pick":
            self.tg.answer(cb["id"])
            self.order(arg)
        elif action == "undo":
            slug, _, pick_id = arg.partition(":")
            try:
                line = self.stock.undo(slug, pick_id)
            except StockError as e:
                return self.tg.answer(cb["id"], str(e))
            self.tg.answer(cb["id"], "put back")
            self.tg.clear_buttons(self.chat_id, msg["message_id"])
            self.say(f"↩️ put <code>{html.escape(line)}</code> back into <b>{html.escape(slug)}</b>")
        elif action == "delete":
            self.tg.answer(cb["id"])
            self.tg.clear_buttons(self.chat_id, msg["message_id"])
            n = self.stock.delete(arg)
            self.say(f"🗑 deleted <b>{html.escape(arg)}</b> ({n} unsold names removed; sold log kept)")
        elif action == "keep":
            self.tg.answer(cb["id"], "kept")
            self.tg.clear_buttons(self.chat_id, msg["message_id"])
        elif action == "menu":
            self.tg.answer(cb["id"])
            self.menu()
        else:
            self.tg.answer(cb["id"])

    def _message(self, msg: dict) -> None:
        if not self._mine(msg.get("chat", {})):
            return
        if "document" in msg:
            return self._upload(msg)
        text = (msg.get("text") or "").strip()
        if not text:
            return
        if text.startswith("/"):
            cmd, _, arg = text.partition(" ")
            return self._command(cmd.split("@")[0].lower(), arg.strip())
        if self.adding:
            return self._add(self.adding, text)
        self.say("send /menu for listing buttons, or /help")

    def _command(self, cmd: str, arg: str) -> None:
        if cmd in ("/start", "/help"):
            self.say(HELP)
        elif cmd == "/get":
            if not arg:
                return self.menu()
            slug = self._existing(arg)
            if slug:
                self.order(slug)
        elif cmd == "/menu":
            self.menu()
        elif cmd == "/stock":
            listings = self.stock.listings()
            lines = [f"{'📦' if n else '🚫'} <b>{html.escape(s)}</b>: {n}" for s, n in listings.items()]
            self.say("\n".join(lines) or "no listings yet")
        elif cmd == "/new":
            if not arg:
                return self.say("usage: /new <i>name</i>  (e.g. /new english)")
            slug = self.stock.create(arg)
            self.adding = slug
            self.say(f"✅ made <b>{slug}</b>. now paste usernames (one per line) or send a .txt. /cancel when done")
        elif cmd == "/add":
            slug = self._existing(arg)
            if slug:
                self.adding = slug
                self.say(f"adding to <b>{slug}</b>: paste usernames or send a .txt. /cancel when done")
        elif cmd == "/delete":
            slug = self._existing(arg)
            if slug:
                n = self.stock.listings()[slug]
                self.say(f"delete <b>{slug}</b> and its {n} unsold names?",
                         [[("🗑 yes, delete", f"delete:{slug}"), ("keep it", "keep:")]])
        elif cmd == "/cancel":
            self.adding = None
            self.say("ok, stopped adding")
        else:
            self.say("don't know that one. /help")

    def _existing(self, name: str) -> str | None:
        listings = self.stock.listings()
        if not name:
            self.say("which listing? " + (", ".join(listings) or "(none yet, use /new)"))
            return None
        try:
            slug = slugify(name)
        except StockError as e:
            self.say(html.escape(str(e)))
            return None
        if slug not in listings:
            self.say(f"no listing called <b>{html.escape(slug)}</b>. you have: {html.escape(', '.join(listings)) or 'none'}")
            return None
        return slug

    def _upload(self, msg: dict) -> None:
        doc = msg["document"]
        caption = (msg.get("caption") or "").strip()
        if not doc.get("file_name", "").lower().endswith(".txt"):
            return self.say("send a .txt file (one username per line)")
        if caption:
            try:
                slug = slugify(caption)
            except StockError as e:
                return self.say(html.escape(str(e)))
            if slug not in self.stock.listings():
                self.stock.create(slug)
                self.say(f"✅ made new listing <b>{slug}</b>. get names from it with /get {slug}")
        elif self.adding:
            slug = self.adding
        else:
            return self.say("which listing is this for? send the .txt again with the listing name as the caption")
        data = self.tg.download(doc["file_id"], MAX_UPLOAD)
        self._add(slug, data.decode("utf-8", errors="replace"))

    def _add(self, slug: str, text: str) -> None:
        r = self.stock.add(slug, text)
        parts = [f"➕ added {r['added']} to <b>{slug}</b> · {r['left']} in stock"]
        if r["duplicates"]:
            parts.append(f"skipped {r['duplicates']} already in stock")
        if r["previously_sold"]:
            names = ", ".join(r["previously_sold"][:10])
            parts.append(f"⚠️ sold before: <code>{html.escape(names)}</code>")
        self.say("\n".join(parts))

    # -- main loop ------------------------------------------------------------

    def run(self) -> None:
        # Drop anything queued while the bot was off so an old tap can't pick a name.
        backlog = self.tg.call("getUpdates", offset=-1, timeout=0)
        offset = backlog[-1]["update_id"] + 1 if backlog else None
        self.say("🟢 bot online. /menu for listings" + (" (ignored taps sent while I was off)" if backlog else ""))
        while True:
            try:
                for up in self.tg.updates(offset):
                    offset = up["update_id"] + 1
                    self.handle(up)
            except TelegramError as e:
                log.warning("polling error: %s", e)
                time.sleep(5)
