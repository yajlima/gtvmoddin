"""`notify-mcp` runs the MCP server; `notify-mcp setup` finds your chat id;
`notify-mcp test [--call]` sends a test message (and call)."""

from __future__ import annotations

import sys

from .channels import CallMeBot, Config, NotifyError, Telegram


def setup(config: Config) -> int:
    tg = Telegram(config)
    me = tg._call("getMe")
    print(f"Bot: @{me['username']}")
    chats = {}
    for up in tg._call("getUpdates", timeout=0):
        chat = (up.get("message") or {}).get("chat")
        if chat:
            chats[chat["id"]] = chat
    if not chats:
        print(f"No messages yet. Open https://t.me/{me['username']}, press Start, "
              "send it any message, then run this again.")
        return 1
    for chat in chats.values():
        who = " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")])) or chat.get("title")
        user = f" (@{chat['username']})" if chat.get("username") else ""
        print(f"TELEGRAM_CHAT_ID={chat['id']}    # {who}{user}")
    return 0


def test(config: Config, call: bool) -> int:
    Telegram(config).send("👋 notify-mcp test: your agents can reach you here.")
    print("Sent a test message.")
    if call:
        print(CallMeBot(config).call("This is a test call from notify M C P.", repeat=1))
    return 0


def main() -> None:
    config = Config.from_env()
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        if cmd == "setup":
            sys.exit(setup(config))
        if cmd == "test":
            sys.exit(test(config, "--call" in sys.argv))
    except NotifyError as e:
        sys.exit(f"error: {e}")
    if cmd:
        sys.exit(__doc__)
    from .server import create_server

    create_server(config).run("stdio")


if __name__ == "__main__":
    main()
