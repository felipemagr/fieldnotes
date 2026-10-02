#!/usr/bin/env bash
# Play a mock call through the real audio path, no second person needed.
#
# CLIENT lines are spoken by a macOS voice straight into BlackHole, as a call app would deliver
# them. ME lines are shown for you to read into your mic; press Enter when you finish each one.
# Start `uv run fieldnotes run --name mock` first, in another terminal.
#
#   scripts/mock_call.sh [transcript]       default: demo/mock_call.txt
#   scripts/mock_call.sh --hands-free       ME lines spoken through your speakers for the mic
#                                           (no headphones, keep the room quiet)
set -euo pipefail
cd "$(dirname "$0")/.."

HANDS_FREE=0
FILE=demo/mock_call.txt
for arg in "$@"; do
  case "$arg" in
    --hands-free) HANDS_FREE=1 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) FILE="$arg" ;;
  esac
done

DEVICE="${FIELDNOTES_CLIENT_DEVICE:-BlackHole 2ch}"
CLIENT_VOICE="${CLIENT_VOICE:-Samantha}"
ME_VOICE="${ME_VOICE:-Daniel}"
say -a '?' | grep -q "$DEVICE" || { echo "Output device '$DEVICE' not found. Run ./install.sh."; exit 1; }

echo "Playing $FILE. CLIENT speaks into '$DEVICE'."
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in
    CLIENT:*)
      text="${line#CLIENT:}"
      printf '\033[1mCLIENT\033[0m%s\n' "$text"
      say -a "$DEVICE" -v "$CLIENT_VOICE" "$text"
      sleep 1.2  # a pause, so the end of the turn is detected
      ;;
    ME:*)
      text="${line#ME:}"
      if [ "$HANDS_FREE" = 1 ]; then
        printf '\033[2mME%s\033[0m\n' "$text"
        say -v "$ME_VOICE" "$text"
        sleep 1.2
      else
        printf '\033[33mYOU, read aloud:\033[0m%s  ' "$text"
        read -r _ </dev/tty
      fi
      ;;
  esac
done <"$FILE"
echo "Done. Click End call in the panel for the report."
