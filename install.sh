#!/usr/bin/env bash
# Install everything Fieldnotes needs on a Mac with Apple Silicon. Safe to run again.
#
#   ./install.sh          asks before the audio driver and the 1.6 GB model
#   ./install.sh --yes    no questions
set -euo pipefail
cd "$(dirname "$0")"

YES=0
for arg in "$@"; do
  case "$arg" in
    --yes|-y) YES=1 ;;
    -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
    *) echo "Unknown option: $arg (see --help)"; exit 2 ;;
  esac
done

bold() { printf '\n\033[1m%s\033[0m\n' "$*"; }
ok() { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
fail() { printf '  \033[31m✗\033[0m %s\n' "$*"; exit 1; }
ask() {  # ask "question" -> 0 for yes
  [ "$YES" = 1 ] && return 0
  read -r -p "  $1 [y/N] " reply
  [[ "$reply" =~ ^[Yy]$ ]]
}

bold "1/7 This Mac"
[ "$(uname -s)" = "Darwin" ] || fail "Fieldnotes runs on macOS."
[ "$(uname -m)" = "arm64" ] || fail "Fieldnotes needs Apple Silicon (on-device Whisper runs on MLX)."
ok "Apple Silicon"
if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  fail "ANTHROPIC_API_KEY is set: Fieldnotes would bill API credits. Run: unset ANTHROPIC_API_KEY"
fi
ok "ANTHROPIC_API_KEY not set"

bold "2/7 Homebrew and uv"
command -v brew >/dev/null || fail "Homebrew is missing. Install it from https://brew.sh and run this again."
ok "Homebrew"
if command -v uv >/dev/null; then ok "uv $(uv --version | cut -d' ' -f2)"
else brew install uv && ok "uv installed"; fi

bold "3/7 Python packages"
UV_HTTP_TIMEOUT=300 uv sync --all-extras --quiet
ok "dependencies installed (.venv)"

bold "4/7 Claude login (your subscription)"
CLAUDE="$(uv run python -c 'import claude_agent_sdk, pathlib; print(pathlib.Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude")')"
[ -x "$CLAUDE" ] || CLAUDE="$(command -v claude || true)"
[ -n "$CLAUDE" ] || fail "Claude Code CLI not found."
status_json="$("$CLAUDE" auth status --json 2>/dev/null || echo '{}')"
read -r logged_in method < <(printf '%s' "$status_json" | uv run python -c '
import json, sys
d = json.loads(sys.stdin.read() or "{}")
print(str(d.get("loggedIn", False)).lower(), d.get("authMethod", "none"))')
if [ "$logged_in" != "true" ]; then
  warn "Not logged in. Opening the Claude login (choose your Claude.ai account)…"
  "$CLAUDE" auth login
  read -r logged_in method < <("$CLAUDE" auth status --json | uv run python -c '
import json, sys; d = json.load(sys.stdin); print(str(d.get("loggedIn")).lower(), d.get("authMethod"))')
  [ "$logged_in" = "true" ] || fail "Still not logged in."
fi
if [ "$method" = "claude.ai" ]; then ok "logged in with Claude.ai (subscription, no API credits)"
else warn "logged in with '$method', not Claude.ai: that may bill API credits."; fi

bold "5/7 API docs"
uv run fieldnotes docs pull | sed 's/^/  /'

bold "6/7 Audio"
if uv run fieldnotes devices 2>/dev/null | grep -q "client channel"; then
  ok "BlackHole 2ch found"
elif ask "Install the BlackHole 2ch audio driver? (asks for your Mac password)"; then
  brew install --cask blackhole-2ch
  sudo killall coreaudiod || true
  ok "BlackHole installed. Next: create the Multi-Output Device (README, Audio setup)."
else
  warn "BlackHole skipped: live calls need it (brew install --cask blackhole-2ch)."
fi
model="$(uv run python -c 'from fieldnotes.settings import get_settings; print(get_settings().whisper_model)')"
snapshots="$HOME/.cache/huggingface/hub/models--${model//\//--}/snapshots"
# The weights file, not the folder: an interrupted download leaves the folder behind.
if compgen -G "$snapshots/*/weights.safetensors" >/dev/null || compgen -G "$snapshots/*/weights.npz" >/dev/null; then
  ok "Whisper model already downloaded ($model)"
elif ask "Download the Whisper model $model now (about 1.6 GB)?"; then
  uv run python -c '
from fieldnotes.adapters.stt_mlx_whisper import MlxWhisperTranscriber
from fieldnotes.settings import get_settings
s = get_settings()
MlxWhisperTranscriber(s.whisper_model, s.language).warm_up()'
  ok "Whisper model ready"
else
  warn "Whisper model not downloaded: the first live call downloads it (slow start)."
fi

bold "7/7 Check"
if uv run pytest -q >/tmp/fieldnotes-tests.log 2>&1; then
  ok "tests pass ($(tail -1 /tmp/fieldnotes-tests.log))"
else
  fail "tests failed, see /tmp/fieldnotes-tests.log"
fi

bold "Ready"
cat <<'EOF'
  Demo:  terminal 1: uv run fieldnotes run --name demo
         terminal 2: scripts/mock_call.sh       (headphones on)
EOF
