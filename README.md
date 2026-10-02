# Fieldnotes

**A local call assistant for engineers who integrate client data.** Fieldnotes listens to a live
client call on your Mac, transcribes it on-device, and keeps a live board of what the client
needs, how each need maps to your platform's API, and what to ask next. When the call ends it
writes a report with an integration plan and a draft follow-up email.

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)](pyproject.toml)
[![macOS · Apple Silicon](https://img.shields.io/badge/macOS-Apple%20Silicon-lightgrey)](#requirements)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

```
 CLIENT  Our loan tape is an Excel export we cannot change. Dates are dd/mm/yyyy.
 ──────────────────────────────────────────────────────────────────────────────
 Ask next      What does a blank DPD mean: no payment due yet, or unknown?
 How it maps   Excel tape → file adapter → POST /v2/declarations   #declaration-flow
               Validate first → dry_run: true                       #dry-run
 Route to Ops  Higher advance rate for clean, on-time data
 Risks         Day and month swapped if a date is parsed with the wrong locale
```

## Why

Forward deployed and solutions engineers spend client calls working out how messy data (Excel
loan tapes, nightly SFTP files, webhooks) fits a platform's API, while also taking notes and
thinking of the next question. Fieldnotes does the bookkeeping:

- **Grounded in your docs.** It crawls the platform's API documentation once. Every mapping
  names a documented endpoint and links to the section it came from, or says "not in docs, ask".
- **Finds the gaps.** Questions target what the client has not said yet: formats, delivery
  channel, identifiers, blank fields, time zones, restatements. A question drops off the board
  once the client answers it.
- **Knows its lane.** Commercial and credit-agreement topics (pricing, advance rates,
  eligibility, waterfalls) go to *Route to Ops* rather than being answered.
- **Fast.** Suggestions reach the screen about 2–4 seconds after the client stops talking.

## Privacy by design

- **Local audio.** Capture, voice detection and speech-to-text run on your Mac. Audio is never
  written to disk.
- **Short retention.** Transcripts stay in memory unless you opt in to keeping them, and kept
  transcripts are deleted after 7 days.
- **Nothing goes out.** The report and the email are drafts for you to edit. Fieldnotes never
  sends anything to the client.
- **No extra cost.** The model runs through the Claude Agent SDK on your existing Claude Code
  login. Fieldnotes refuses to start if `ANTHROPIC_API_KEY` is set, so it can never bill API
  credits by accident.

## Requirements

- macOS on Apple Silicon (live transcription uses [MLX](https://github.com/ml-explore/mlx)).
  Replay mode runs on any Mac.
- [Homebrew](https://brew.sh)
- A Claude subscription, logged in through [Claude Code](https://code.claude.com)
- For live calls: [BlackHole 2ch](https://github.com/ExistentialAudio/BlackHole) and headphones

## Quick start

```sh
git clone git@github.com:felipemagr/fieldnotes.git && cd fieldnotes
./install.sh
uv run fieldnotes run --replay demo/mock_call.txt
```

`install.sh` checks the Mac, installs `uv` and the Python dependencies, and verifies that Claude
is logged in with a Claude.ai account rather than an API key. It also pulls the API docs, offers
to install BlackHole and download the Whisper model (~1.6 GB), and finishes by running the
tests. It is safe to run again. Use `./install.sh --no-audio` to skip the audio stack.

The panel opens at <http://127.0.0.1:8765> and the mock call starts playing.

## Usage

| Command | What it does |
|---|---|
| `fieldnotes run` | Live call: mic and call audio, transcription, live panel |
| `fieldnotes run --replay FILE` | Play a transcript at speaking pace instead of live audio |
| `fieldnotes run --fake-llm` | Canned answers, no model calls (UI work, offline demos) |
| `fieldnotes run --name "acme"` | Name the call (used in the report file name) |
| `fieldnotes run --refresh-docs` | Re-crawl the docs before the call |
| `fieldnotes docs pull [URL]` | Crawl and cache a docs site |
| `fieldnotes devices` | List audio inputs and show which one is the client channel |
| `fieldnotes check-audio` | Live level meters for both channels |

Prefix commands with `uv run`, or activate `.venv`.

### Live call setup

Fieldnotes hears two channels: your microphone is **ME** and the call app's output is **CLIENT**.
Speaker identity comes from the channel, so no diarization is needed.

1. Install BlackHole (`./install.sh` offers it, or `brew install --cask blackhole-2ch`).
2. In **Audio MIDI Setup**, click **+**, then **Create Multi-Output Device**. Select your
   headphones and *BlackHole 2ch*, put the headphones first, and enable drift correction on
   BlackHole.
3. In the call app (Meet, Zoom, Teams), set the **speaker** to the Multi-Output Device. You still
   hear the call, and BlackHole receives a copy. Leave the microphone unchanged.
4. Run `uv run fieldnotes check-audio`. Both meters should move.
5. Start the call with `uv run fieldnotes run --name "client name"`.

Use headphones. With speakers, your microphone also picks up the client and attributes their
words to you.

To rehearse without a second person, run `scripts/mock_call.sh` in another terminal: a macOS
voice speaks the CLIENT lines of `demo/mock_call.txt` into BlackHole and you read the ME lines
into your microphone. Everything else is real (VAD, Whisper, Claude).

### Test scenarios

`uv run python scripts/make_synthetic.py` writes `data/synthetic/`. It contains replayable calls
(nightly SFTP deltas, noisy transcription, a client who only negotiates, a one-word-answers
client) together with the files those clients describe: a Spanish-locale loan tape with blank
and inconsistent fields, out-of-order duplicate Stripe webhooks, and a contracts index with
mixed file names. `data/synthetic/calls/EXPECTED.md` describes what a good panel shows for each.

## Configuration

Settings are read from the environment or a `.env` file, prefixed with `FIELDNOTES_`. See
[`.env.example`](.env.example) for the full list.

| Variable | Default | Purpose |
|---|---|---|
| `FIELDNOTES_MODEL` | `haiku` | `haiku` is fast; `sonnet` is slower and stronger |
| `FIELDNOTES_DOCS_URL` | `https://docs.fence.finance/` | Docs to ground suggestions in |
| `FIELDNOTES_DOCS_TTL_DAYS` | `7` | Re-crawl the docs after this many days |
| `FIELDNOTES_CLIENT_DEVICE` | `BlackHole 2ch` | Input that carries the call audio |
| `FIELDNOTES_MIC_DEVICE` | system default | Your microphone |
| `FIELDNOTES_END_OF_TURN_MS` | `700` | Silence that ends a turn |
| `FIELDNOTES_LANGUAGE` | `en` | Speech-to-text language hint |
| `FIELDNOTES_TRIGGER_MIN_WORDS` | `15` | Client turn length that triggers an update |
| `FIELDNOTES_LLM_TIMEOUT_S` | `30` | Time limit per model call |
| `FIELDNOTES_KEEP_TRANSCRIPTS` | `false` | Keep transcripts on disk |
| `FIELDNOTES_RETENTION_DAYS` | `7` | Delete kept transcripts after this many days |

Fieldnotes was built against [Fence's API docs](https://docs.fence.finance/), but it works with any
documentation site: run `fieldnotes docs pull https://docs.example.com/` and set
`FIELDNOTES_DOCS_URL`. The prompt in `src/fieldnotes/app/brain.py` carries the domain hints (asset-backed
finance) and is the place to adapt them.

## How it works

```
 microphone ──┐
              ├─▶ Silero VAD ─▶ mlx-whisper ─▶ turn ─▶ trigger ─▶ Claude (Agent SDK) ─▶ board ─▶ panel (SSE)
 BlackHole ───┘   end of turn    on-device             batches     docs loaded once     merge,
                  after 700 ms   transcription         new turns   JSON per update      dedupe
```

1. **Capture and segment.** Each channel goes through Silero VAD. A turn ends after 700 ms of
   silence, and blips under 0.5 s are dropped.
2. **Transcribe.** `whisper-large-v3-turbo` runs on the GPU through MLX, in a worker thread, so
   capture never waits.
3. **Trigger.** A client turn of 15 or more words, or a question, sends the new turns to the
   model. Your own turns travel as context. Turns that arrive while the model is busy are
   batched into the next request.
4. **Analyse.** One Claude session per call, with all tools disabled. The docs are sent once and
   every update carries only the new turns plus the open questions. Each answer is a validated
   JSON object; invalid answers are retried once.
5. **Board.** Updates merge into five sections, with duplicates and answered questions removed.
   You can pin or dismiss items.
6. **Report.** *End call* finishes transcribing, then writes `calls/<date>-<name>.md` from the
   full transcript and your board.

Every model call and every wait has a time limit. A stalled call skips one update and the session
restarts; *End call* always produces a report.

### Project layout

```
src/fieldnotes/
  domain/     pure logic: turns, trigger rules, board merge, JSON parsing (no I/O)
  ports.py    Protocols for audio, transcription, turn sources and the model
  adapters/   sounddevice, Silero VAD, mlx-whisper, Agent SDK, docs crawler, replay, fakes
  app/        the Brain (prompt), the call pipeline, the FastAPI server, the CLI
  web/        the panel: one HTML page, plain JS and CSS, no build step
```

Business logic depends only on the Protocols in `ports.py`, so every device and service can be
replaced by a fake. Replay mode and the test suite rely on that.

## Development

```sh
uv sync --all-extras
uv run pytest                                  # ~5 s; no model, no audio devices
uv run ruff check . && uv run ruff format .
uv run fieldnotes run --replay demo/mock_call.txt --fake-llm
```

Contributions are welcome. Please open an issue first for larger changes, and keep the rules that
make Fieldnotes trustworthy: no audio on disk, nothing sent automatically,
and a time limit on anything that waits.

[`docs/demo.md`](docs/demo.md) has a two-minute script for presenting Fieldnotes.

## Notes

Fieldnotes is a personal productivity tool. It is not affiliated with Fence or Anthropic. It starts
transcribing as soon as it runs: telling people you transcribe a call, and following the
recording laws that apply to you, is your responsibility. The Agent SDK's terms do not
allow offering claude.ai login to other users of a product, so each user runs Fieldnotes on their
own Claude login.

## License

[MIT](LICENSE) © 2026 Felipe Macías
