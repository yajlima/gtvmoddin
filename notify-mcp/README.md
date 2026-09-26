# notify-mcp

An [MCP](https://modelcontextprotocol.io) server that lets your AI agents reach you on your phone: **text you, call you, or ask you a question and wait for your answer.**

- Texts and questions go through a Telegram bot (official Bot API, free).
- Calls go through [CallMeBot](https://www.callmebot.com/telegram-call-api/), a free third-party service that rings your Telegram and reads the message aloud.

No public URL, webhook or tunnel needed: the server polls Telegram for your replies.

## Tools

| Tool | What it does |
|---|---|
| `notify_me(message, urgency)` | `"low"` = silent text, `"normal"` = text, `"urgent"` = text **and** a call |
| `call_me(message, repeat)` | Voice call that reads the message (max 256 chars). Missed it? You get it as a text |
| `ask_me(question, options, timeout_seconds)` | Sends a question (with tap-to-answer buttons if you pass `options`) and waits for your reply |

## Setup (about 5 minutes)

### 1. Make a bot

1. In Telegram, message [@BotFather](https://t.me/BotFather), send `/newbot` and follow the prompts.
2. Copy the token it gives you (looks like `123456:ABC-...`).
3. Open your new bot, press **Start**, and send it any message.

### 2. Install and find your chat id

```bash
pip install ./notify-mcp          # Python 3.10+
TELEGRAM_BOT_TOKEN=123456:ABC... notify-mcp setup
```

It prints a line like `TELEGRAM_CHAT_ID=987654321`. The bot only ever messages, and only accepts answers from, that chat.

### 3. Turn on calls (optional)

1. Make sure you have a Telegram username (Settings → Username).
2. Authorize CallMeBot to call you: message [@CallMeBot_txtbot](https://t.me/CallMeBot_txtbot) and send `/start`.

### 4. Test it

```bash
export TELEGRAM_BOT_TOKEN=123456:ABC... TELEGRAM_CHAT_ID=987654321 TELEGRAM_USERNAME=@yourname
notify-mcp test --call
```

You should get a text and then a call.

### 5. Add it to your agent

**Claude Code**

```bash
claude mcp add notify \
  -e TELEGRAM_BOT_TOKEN=123456:ABC... \
  -e TELEGRAM_CHAT_ID=987654321 \
  -e TELEGRAM_USERNAME=@yourname \
  -- notify-mcp
```

**Claude Desktop / Cursor**

```json
{
  "mcpServers": {
    "notify": {
      "command": "notify-mcp",
      "env": {
        "TELEGRAM_BOT_TOKEN": "123456:ABC...",
        "TELEGRAM_CHAT_ID": "987654321",
        "TELEGRAM_USERNAME": "@yourname"
      }
    }
  }
}
```

Then tell your agent something like: *"If you get stuck or need a decision, use ask_me. If something is on fire, call me."*

## Configuration

| Variable | Required | Notes |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | yes | From @BotFather |
| `TELEGRAM_CHAT_ID` | yes | From `notify-mcp setup` |
| `TELEGRAM_USERNAME` | for calls | Your `@username` (or phone number with country code) |
| `CALLMEBOT_LANG` | no | TTS voice, e.g. `en-US-Standard-B` (default: CallMeBot's English voice) |

## Things to know

- **CallMeBot is a third-party service**, not part of Telegram. The text of every call passes through their servers, so don't put passwords or secrets in call messages. The free tier is for personal use only.
- Per CallMeBot, **the iOS Telegram app has a bug** where call audio sometimes doesn't play. You'll still see the call, and a missed call sends the text.
- **Use a dedicated bot** for this. Only one program can poll a bot for replies at a time, and a bot with a webhook set can't be polled at all.
- `ask_me` holds the tool call open while it waits. If your MCP client times out long tool calls, use a shorter `timeout_seconds`.
- Your bot token is a secret. Keep it in your MCP client config or environment and out of git.

## Development

```bash
pip install -e "./notify-mcp[test]"
cd notify-mcp && pytest
```

Tests run against a fake Telegram API and a fake CallMeBot, including a full MCP session over stdio. Tested on `mcp` 1.x and 2.x.
