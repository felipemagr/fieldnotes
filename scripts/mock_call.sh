#!/usr/bin/env bash
# The demo: a mock client call through the real audio path.
#
# A macOS voice plays the client. It speaks into BlackHole, as a call app would, and into your
# headphones, so you hear the client. You read your lines into the mic and press Enter after
# each one. Start `uv run fieldnotes run --name demo` in another terminal first. Headphones on:
# with speakers, the mic hears the client too.
#
#   scripts/mock_call.sh
set -euo pipefail
cd "$(dirname "$0")/.."

DEVICE="${FIELDNOTES_CLIENT_DEVICE:-BlackHole 2ch}"
VOICE="${CLIENT_VOICE:-Samantha}"
say -a '?' | grep -q "$DEVICE" || { echo "Output device '$DEVICE' not found. Run ./install.sh."; exit 1; }

OUTPUT="$(system_profiler SPAudioDataType 2>/dev/null |
  awk '/^        [^ ].*:$/ {name=$0} /Default Output Device: Yes/ {gsub(/^ +|:$/, "", name); print name}')"
if [ "$OUTPUT" = "$DEVICE" ]; then
  echo "Your Mac's sound output is $DEVICE, so you would not hear the client. Pick your headphones."
  exit 1
fi

client() {
  if [[ "$OUTPUT" == *Multi-Output* ]]; then
    say -v "$VOICE" "$1"  # the Multi-Output Device already feeds both BlackHole and you
  else
    say -a "$DEVICE" -v "$VOICE" "$1" &  # same voice and rate on both outputs: in step
    say -v "$VOICE" "$1"
    wait
  fi
}

echo "Mock call, client heard on: $OUTPUT. Your lines are in yellow: read, then press Enter."
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in
    CLIENT:*)
      printf '\033[1mCLIENT\033[0m%s\n' "${line#CLIENT:}"
      client "${line#CLIENT:}"
      sleep 1  # a natural pause, so the end of the turn is detected
      ;;
    ME:*)
      printf '\033[33mYOU:\033[0m%s  ' "${line#ME:}"
      read -r _ </dev/tty
      ;;
  esac
done <demo/mock_call.txt
echo "Done. Click End call in the panel for the report."
