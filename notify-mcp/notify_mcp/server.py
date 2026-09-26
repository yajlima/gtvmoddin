"""MCP server that lets AI agents text you, call you, and ask you questions."""

from __future__ import annotations

import functools

import anyio.to_thread

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as _Server
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server
    from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from .channels import CallMeBot, Config, NotifyError, Telegram

INSTRUCTIONS = """\
Reach the human who runs you on their phone. Use notify_me for updates, ask_me
when you are blocked on a decision only they can make, and call_me (or
notify_me with urgency="urgent") only for things that genuinely can't wait:
calls interrupt them. Keep messages short and say what you need.
"""

NOTIFY = ToolAnnotations.model_validate({"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True})


def create_server(config: Config, telegram: Telegram | None = None, callmebot: CallMeBot | None = None):
    telegram = telegram or Telegram(config)
    callmebot = callmebot or CallMeBot(config)
    mcp = _Server("notify", instructions=INSTRUCTIONS)

    async def run(fn, *args, **kwargs):
        try:
            return await anyio.to_thread.run_sync(functools.partial(fn, *args, **kwargs))
        except NotifyError as e:
            raise ToolError(str(e)) from None

    @mcp.tool(annotations=NOTIFY)
    async def notify_me(message: str, urgency: str = "normal") -> dict:
        """Text the user on Telegram. urgency: "low" (silent notification), "normal",
        or "urgent" (text plus a voice call that reads the message aloud)."""
        if urgency not in ("low", "normal", "urgent"):
            raise ToolError('urgency must be "low", "normal" or "urgent"')
        msg_id = await run(telegram.send, message, silent=urgency == "low")
        result: dict = {"sent": True, "message_id": msg_id}
        if urgency == "urgent":
            try:
                result["call"] = await run(callmebot.call, message, text_copy="no")
            except ToolError as e:
                result["call_error"] = str(e)  # the text still went through
        return result

    @mcp.tool(annotations=NOTIFY)
    async def call_me(message: str, repeat: int = 2) -> dict:
        """Phone the user via a Telegram voice call and read the message aloud
        (max 256 characters, repeated `repeat` times). If they miss the call they
        get the message as text."""
        return {"called": True, "status": await run(callmebot.call, message, repeat)}

    @mcp.tool(annotations=NOTIFY)
    async def ask_me(question: str, options: list[str] | None = None,
                     timeout_seconds: int = 300) -> dict:
        """Ask the user a question on Telegram and wait for the answer. With `options`
        they get tap-to-answer buttons; they can also just type a reply. Waits up to
        timeout_seconds (max 3600)."""
        return await run(telegram.ask, question, options, max(10, min(timeout_seconds, 3600)))

    return mcp
