"""username-bot                 run the Telegram bot
username-bot order LISTING   pick a username for LISTING and send it to Telegram
                             (hook for scripts, e.g. an Eldorado order watcher)
username-bot stock           print how many names each listing has left

Env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, STOCK_DIR (default ./stock),
     LOW_STOCK (warn at or below this many, default 3), TELEGRAM_API_URL (tests)."""

from __future__ import annotations

import logging
import os
import sys

from .bot import Bot
from .stock import Stock, StockError, slugify
from .telegram import Telegram, TelegramError


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    env = os.environ.get
    args = sys.argv[1:]
    stock = Stock(env("STOCK_DIR", "stock"))

    if args[:1] == ["stock"]:
        for slug, n in stock.listings().items():
            print(f"{slug}\t{n}")
        return
    if args and args[0] not in ("order",):
        sys.exit(__doc__)

    chat_id = env("TELEGRAM_CHAT_ID", "")
    try:
        if not chat_id:
            raise TelegramError("set TELEGRAM_CHAT_ID")
        tg = Telegram(env("TELEGRAM_BOT_TOKEN", ""), env("TELEGRAM_API_URL", "https://api.telegram.org"))
        bot = Bot(tg, stock, chat_id, int(env("LOW_STOCK", "3")))
        if args[:1] == ["order"]:
            if len(args) != 2:
                sys.exit("usage: username-bot order LISTING")
            pick = bot.order(slugify(args[1]))
            print(f"sent a {pick['listing']} username ({pick['left']} left)")
        else:
            bot.run()
    except (TelegramError, StockError) as e:
        sys.exit(f"error: {e}")
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
