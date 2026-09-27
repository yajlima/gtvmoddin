#!/usr/bin/env bash
# Install (or update) username-bot on a Linux box and run it as a systemd service.
#
#   ./install.sh              install or update, asks for anything it needs
#   ./install.sh --uninstall  stop and remove the service and app (keeps your stock + config)
#
# Skip the questions by setting TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID and
# optionally STOCK_DIR / LOW_STOCK before running it.

set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${INSTALL_DIR:-$HOME/.local/share/username-bot}"
VENV="$APP_DIR/venv"
ENV_FILE="${ENV_FILE:-$HOME/.config/username-bot.env}"
SERVICE=username-bot
UNIT="/etc/systemd/system/$SERVICE.service"
API="${TELEGRAM_API_URL:-https://api.telegram.org}"

say()  { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }

have_systemd() { command -v systemctl >/dev/null && [ -d /run/systemd/system ]; }

sudo_() { if [ "$(id -u)" -eq 0 ]; then "$@"; else sudo "$@"; fi; }

# Telegram helpers (python so there's no curl/jq dependency)
tg() {  # tg METHOD -> prints JSON result or exits 1
  "$VENV/bin/python" - "$API" "$TOKEN" "$1" <<'PY'
import json, sys, urllib.request, urllib.error
api, token, method = sys.argv[1:]
try:
    with urllib.request.urlopen(f"{api}/bot{token}/{method}", timeout=20) as r:
        resp = json.load(r)
except urllib.error.HTTPError as e:
    resp = json.load(e)
except Exception as e:
    print(f"network error: {e}", file=sys.stderr); sys.exit(1)
if not resp.get("ok"):
    print(resp.get("description", "error"), file=sys.stderr); sys.exit(1)
print(json.dumps(resp["result"]))
PY
}

json_get() { "$VENV/bin/python" -c "import json,sys; d=json.load(sys.stdin); print($1)"; }

uninstall() {
  if have_systemd && [ -f "$UNIT" ]; then
    say "stopping and removing the service"
    sudo_ systemctl disable --now "$SERVICE" || true
    sudo_ rm -f "$UNIT"
    sudo_ systemctl daemon-reload
  fi
  rm -rf "$APP_DIR"
  say "removed. your stock and $ENV_FILE were kept"
  exit 0
}

[ "${1:-}" = "--uninstall" ] && uninstall
[ -n "${1:-}" ] && die "unknown option: $1 (use --uninstall or nothing)"
[ "$(uname -s)" = Linux ] || die "this installer is for Linux"
[ -f "$SRC_DIR/pyproject.toml" ] || die "run this from the username-bot folder"

# 1. python
PY=$(command -v python3 || true)
[ -n "$PY" ] || die "python3 not found. install it (e.g. sudo apt install python3 python3-venv)"
"$PY" -c 'import sys; sys.exit(sys.version_info < (3, 10))' \
  || die "need python 3.10+, you have $("$PY" --version)"
"$PY" -c 'import venv, ensurepip' 2>/dev/null \
  || die "python venv missing. install it (e.g. sudo apt install python3-venv)"

# 2. app
say "installing to $APP_DIR"
mkdir -p "$APP_DIR"
[ -x "$VENV/bin/python" ] || "$PY" -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet --upgrade "$SRC_DIR"
BIN="$VENV/bin/username-bot"

# 3. config
if [ -f "$ENV_FILE" ] && [ -z "${TELEGRAM_BOT_TOKEN:-}" ]; then
  say "keeping existing config $ENV_FILE"
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

TOKEN="${TELEGRAM_BOT_TOKEN:-}"
ERR=$(mktemp)
trap 'rm -f "$ERR"' EXIT
while :; do
  if [ -z "$TOKEN" ]; then
    echo
    echo "Make a bot with @BotFather in Telegram (/newbot) and paste its token."
    echo "Use a different bot from notify-mcp."
    read -rp "bot token: " TOKEN
  fi
  if ME=$(tg getMe 2>"$ERR"); then
    BOT_NAME=$(echo "$ME" | json_get 'd["username"]')
    say "token works: @$BOT_NAME"
    break
  fi
  warn "token didn't work: $(cat "$ERR")"
  [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && die "fix TELEGRAM_BOT_TOKEN and run again"
  TOKEN=""
done

CHAT_ID="${TELEGRAM_CHAT_ID:-}"
while [ -z "$CHAT_ID" ]; do
  echo
  echo "Open https://t.me/$BOT_NAME in Telegram, press Start, send it any message,"
  read -rp "then press Enter here... " _
  CHAT_ID=$(tg getUpdates | json_get '
next((str(u["message"]["chat"]["id"]) for u in reversed(d) if "message" in u), "")') || CHAT_ID=""
  if [ -n "$CHAT_ID" ]; then say "found your chat id: $CHAT_ID"; else warn "no message yet, try again"; fi
done

STOCK_DIR="${STOCK_DIR:-$HOME/username-stock}"
case "$STOCK_DIR" in /*) ;; *) STOCK_DIR="$HOME/${STOCK_DIR#./}";; esac
LOW_STOCK="${LOW_STOCK:-3}"
mkdir -p "$STOCK_DIR" "$(dirname "$ENV_FILE")"

umask 077
{
  echo "TELEGRAM_BOT_TOKEN=$TOKEN"
  echo "TELEGRAM_CHAT_ID=$CHAT_ID"
  echo "STOCK_DIR=$STOCK_DIR"
  echo "LOW_STOCK=$LOW_STOCK"
  if [ "$API" != "https://api.telegram.org" ]; then echo "TELEGRAM_API_URL=$API"; fi
} > "$ENV_FILE"
chmod 600 "$ENV_FILE"
say "saved config to $ENV_FILE (only you can read it)"

# 4. service
if ! have_systemd; then
  warn "no systemd here, so no service was set up. run it with:"
  echo "  set -a; . $ENV_FILE; set +a; $BIN"
  exit 0
fi

say "setting up the systemd service (may ask for your password)"
sudo_ tee "$UNIT" >/dev/null <<EOF
[Unit]
Description=username-bot
After=network-online.target
Wants=network-online.target

[Service]
User=$(id -un)
EnvironmentFile=$ENV_FILE
ExecStart=$BIN
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
sudo_ systemctl daemon-reload
sudo_ systemctl enable --quiet "$SERVICE"
sudo_ systemctl restart "$SERVICE"
sleep 2

if systemctl is-active --quiet "$SERVICE"; then
  say "username-bot is running 🟢 check Telegram for \"bot online\""
  echo
  echo "  stock folder:  $STOCK_DIR   (back this up)"
  echo "  logs:          journalctl -u $SERVICE -f"
  echo "  restart:       sudo systemctl restart $SERVICE"
  echo "  update:        git pull && ./install.sh"
  echo "  uninstall:     ./install.sh --uninstall"
else
  warn "the service didn't start. last logs:"
  sudo_ journalctl -u "$SERVICE" -n 20 --no-pager || true
  exit 1
fi
