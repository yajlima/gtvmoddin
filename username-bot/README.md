# username-bot

A Telegram bot for selling usernames. Each listing is a `.txt` file of names. When an order comes in, tap that listing's button and the bot hands you a **random** name from it, as its own message so it's easy to copy. The name comes out of the file so you never sell the same one twice.

```
you:  [📦 english (12)]            ← tap the listing that sold
bot:  🛒 english sold · 11 left    [↩️ undo]
bot:  Notch                         ← tap to copy, paste into the order chat
```

- **Random pick, removed from stock.** Picked names go to `<listing>.sold.txt`, a log of what sold and when.
- **Undo** puts the name back if the order gets cancelled.
- **Separate messages.** If a line has more than one detail (`name:extra` or `name|extra`), each part is sent as its own message.
- **Low stock alerts** when a listing is at or below `LOW_STOCK` names, and an out-of-stock warning at 0.
- **Only you.** Messages and taps from any other chat are ignored.
- No dependencies, just Python 3.10+.

## Commands

| Command | What it does |
|---|---|
| `/menu` | A button for each listing, with names left |
| `/stock` | Names left per listing |
| `/new english` | Make a listing, then paste names (one per line) or send a `.txt` |
| `/add english` | Add names to a listing: paste them or send a `.txt` |
| `/cancel` | Stop adding names |
| `/delete english` | Delete a listing (asks first; the sold log is kept) |

Shortcut: send a `.txt` with the listing name as the caption to add it straight to that listing. Duplicates are skipped, and names you've sold before are flagged.

## Setup

1. **Make a bot** with [@BotFather](https://t.me/BotFather) (`/newbot`) and copy the token. Use a different bot from notify-mcp: only one program can read a bot's messages at a time.
2. **Get your chat id.** Message your new bot once, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` and look for `"chat":{"id":...}`. Or use `notify-mcp setup` with this bot's token.
3. **Install and run:**
   ```bash
   pip install ./username-bot
   export TELEGRAM_BOT_TOKEN=123456:ABC... TELEGRAM_CHAT_ID=987654321 STOCK_DIR=~/username-stock
   username-bot
   ```
   You'll get "🟢 bot online". Send `/new english` and paste your names.

Already have `.txt` files? Drop them into `STOCK_DIR` (for example `english.txt`, `random.txt`, `nonumbers.txt`). The filename is the listing name.

## Run it on the homelab (systemd)

`/etc/systemd/system/username-bot.service`:

```ini
[Unit]
Description=username-bot
After=network-online.target
Wants=network-online.target

[Service]
User=youruser
EnvironmentFile=/home/youruser/.config/username-bot.env
ExecStart=/home/youruser/.local/bin/username-bot
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

`/home/youruser/.config/username-bot.env` (run `chmod 600` on it):

```
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=987654321
STOCK_DIR=/home/youruser/username-stock
LOW_STOCK=3
```

Then run `sudo systemctl enable --now username-bot`, and check logs with `journalctl -u username-bot -f`.

When the bot starts, it ignores taps you sent while it was off, so a stale tap can't hand out a name. Just tap again.

## Hooking up automation later

`username-bot order english` does exactly what tapping the button does: it picks a name and sends it to your Telegram. Any script can call it, for example an Eldorado Seller API watcher that runs it when a new order comes in. It's safe to run while the bot is running, because file access is locked.

`username-bot stock` prints the counts, which you can use for restock scripts.

## Things to know

- **Back up `STOCK_DIR`.** It is your inventory. The `.sold.txt` logs are your sales history.
- The bot token controls the bot, so keep it out of git and screenshots.
- Names in stock are stored as plain text on the homelab, so don't expose that folder.

## Development

```bash
pip install -e "./username-bot[test]"
cd username-bot && pytest
```
