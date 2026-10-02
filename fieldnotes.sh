#!/usr/bin/env bash
# Start Fieldnotes with the audio set up, and put the audio back when you stop.
#
#   ./fieldnotes.sh                 a real call: join it in Meet or Zoom, Ctrl+C when it ends
#   ./fieldnotes.sh "acme"          same, naming the call (used for the report file)
#   ./fieldnotes.sh --demo          the mock call: a voice plays the client, you read your lines
#
# While it runs, the Mac's sound goes to your speakers or headphones and to BlackHole, so you hear
# the call and Fieldnotes hears the client. Call apps on "System default" follow it.
set -euo pipefail
cd "$(dirname "$0")"

DEMO=0
NAME="call"
for arg in "$@"; do
  case "$arg" in
    --demo) DEMO=1; NAME="demo" ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) NAME="$arg" ;;
  esac
done

# Run the installed command, not `uv run`: signals must reach Fieldnotes, and uv does not pass
# SIGTERM on to its child.
BIN=.venv/bin/fieldnotes
[ -x "$BIN" ] || { echo "Fieldnotes is not installed: run ./install.sh first."; exit 1; }

# The audio helper is compiled once, and again only when its source changes.
ROUTE=.build/audio_route
if [ ! -x "$ROUTE" ] || [ scripts/audio_route.swift -nt "$ROUTE" ]; then
  mkdir -p .build && swiftc -O scripts/audio_route.swift -o "$ROUTE"
fi

PREVIOUS="$("$ROUTE" start)"
SERVER=""
RESTORED=0
restore() {  # audio first, at once; then let Fieldnotes finish closing
  if [ "$RESTORED" = 0 ]; then
    RESTORED=1
    "$ROUTE" stop "$PREVIOUS"
    echo "Audio back to $("$ROUTE" name)."
  fi
  if [ -n "$SERVER" ] && kill -0 "$SERVER" 2>/dev/null; then
    kill -TERM "$SERVER" 2>/dev/null || true  # background jobs ignore SIGINT in scripts
    for _ in 1 2 3 4 5 6; do kill -0 "$SERVER" 2>/dev/null || return 0; sleep 0.5; done
    kill -KILL "$SERVER" 2>/dev/null || true  # the report was saved at End call; nothing is lost
  fi
}
trap restore EXIT
trap 'exit 130' INT TERM
echo "Audio: your output + BlackHole ($("$ROUTE" name)). It goes back when you stop."

PORT="${FIELDNOTES_PORT:-8765}"
if [ "$DEMO" = 0 ]; then
  # In the background so Ctrl+C reaches this script at once (a foreground child would delay it).
  "$BIN" run --name "$NAME" &
  SERVER=$!
  wait "$SERVER"
  exit
fi

# Demo: Fieldnotes in the background, the mock call here.
LOG="${TMPDIR:-/tmp}/fieldnotes-demo.log"
"$BIN" run --name "$NAME" >"$LOG" 2>&1 &
SERVER=$!
printf "Starting Fieldnotes (log: %s)" "$LOG"
for _ in $(seq 1 60); do
  curl -s -m 1 "localhost:$PORT/api/state" | grep -q '"brain_ready":true' && break
  kill -0 "$SERVER" 2>/dev/null || { echo; tail -20 "$LOG"; exit 1; }
  printf "."
  sleep 1
done
echo " ready."
scripts/mock_call.sh
read -r -p "Click End call in the panel, read the report, then press Enter to finish. " _ </dev/tty
