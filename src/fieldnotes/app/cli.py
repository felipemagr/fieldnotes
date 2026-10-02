"""Command line: `fieldnotes run | devices | check-audio | docs pull`."""

import logging
import time
import webbrowser
from threading import Timer
from typing import Annotated

import typer

from fieldnotes.adapters.llm_agent_sdk import ApiKeyInEnvironment, refuse_api_key
from fieldnotes.settings import get_settings

app = typer.Typer(add_completion=False, no_args_is_help=True)
docs_app = typer.Typer(no_args_is_help=True, help="Fetch and cache the platform's API docs.")
app.add_typer(docs_app, name="docs")

logger = logging.getLogger("fieldnotes")


@app.callback()
def main(verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False) -> None:
    """Listens to a client call, transcribes it locally and suggests what to ask next."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    for noisy in ("httpx", "claude_agent_sdk", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    try:
        refuse_api_key()
    except ApiKeyInEnvironment as e:
        typer.secho(str(e), fg="red", err=True)
        raise typer.Exit(2) from e


def load_docs(url: str, force: bool = False, max_pages: int | None = None):
    """The docs, checked against the site: re-crawled only when a page changed.

    Returns (bundle, changes). Offline, or when the site fails, it falls back to the last crawl.
    """
    from fieldnotes.adapters.docs_crawler import Changes, DocsLibrary, crawl

    s = get_settings()
    library = DocsLibrary(s.docs_dir)
    cached = library.get(url)
    pages = max_pages or s.docs_max_pages
    previous = None if force else cached
    bundle = crawl(url, pages, s.docs_delay_s, max_seconds=s.docs_timeout_s, previous=previous)
    if not bundle.pages:
        if cached is None:
            raise RuntimeError(f"No pages could be fetched from {url}")
        logger.warning("Could not reach %s: using the docs from the last check", url)
        return cached, Changes()
    changes = bundle.changes_since(cached) if cached else Changes(added=["(first crawl)"])
    library.put(bundle)  # also stores the latest ETags, so the next check is a 304
    logger.info("Docs %s: %s", url, changes)
    if bundle.approx_tokens > s.docs_warn_tokens:
        logger.warning("Docs are large (~%d tokens): each call starts slower", bundle.approx_tokens)
    return bundle, changes


@docs_app.command("pull")
def docs_pull(
    url: Annotated[str | None, typer.Argument(help="Start URL (default: docs_url)")] = None,
    force: Annotated[bool, typer.Option(help="Re-download every page")] = False,
    max_pages: Annotated[int | None, typer.Option()] = None,
) -> None:
    """Check the docs for changes and update the local copy."""
    url = url or get_settings().docs_url
    try:
        bundle, changes = load_docs(url, force=force, max_pages=max_pages)
    except RuntimeError as e:
        typer.secho(str(e), fg="red", err=True)
        raise typer.Exit(1) from e
    status = f"updated ({changes})" if changes else "up to date"
    typer.echo(f"Docs {status}. {len(bundle.pages)} page(s), ~{bundle.approx_tokens:,} tokens")
    for page in bundle.pages:
        typer.echo(f"  {page.url}  ({page.title})")


@app.command()
def run(
    name: Annotated[str, typer.Option(help="Call name, used in the report file name")] = "call",
    model: Annotated[str | None, typer.Option(help="sonnet or haiku")] = None,
    docs_url: Annotated[str | None, typer.Option()] = None,
    port: Annotated[int | None, typer.Option()] = None,
    open_browser: Annotated[bool, typer.Option("--open/--no-open")] = True,
) -> None:
    """Start the live panel for one call."""
    import uvicorn

    from fieldnotes.adapters.store import cleanup
    from fieldnotes.app.brain import Brain
    from fieldnotes.app.pipeline import CallSession
    from fieldnotes.app.server import create_app
    from fieldnotes.domain.trigger import TurnTrigger

    s = get_settings()
    cleanup(s.calls_dir, s.retention_days)

    from fieldnotes.adapters.llm_agent_sdk import ClaudeAgentSDKLLM

    source = build_live_source()
    llm = ClaudeAgentSDKLLM(model or s.model)

    url = docs_url or s.docs_url
    session = CallSession(
        source=source,
        brain=Brain(
            llm,
            s.llm_start_timeout_s,
            s.llm_timeout_s,
            s.report_timeout_s,
            teams=s.teams_file.read_text(encoding="utf-8") if s.teams_file else None,
            report_llm=ClaudeAgentSDKLLM(s.report_model) if s.report_model else None,
        ),
        docs_loader=lambda: load_docs(url)[0].markdown,
        calls_dir=s.calls_dir,
        name=name,
        keep_transcripts=s.keep_transcripts,
        trigger=TurnTrigger(s.trigger_min_words, s.debounce_s),
        docs_timeout_s=s.docs_timeout_s,
    )
    port = port or s.port
    address = f"http://{s.host}:{port}"
    typer.echo(f"Fieldnotes panel: {address}")
    if open_browser:
        Timer(1.0, webbrowser.open, [address]).start()
    uvicorn.run(create_app(session), host=s.host, port=port, log_level="warning")


def build_live_source():
    """Mic + BlackHole, Silero VAD per channel, Whisper loaded and warmed before the call."""
    from fieldnotes.adapters.audio_sounddevice import DeviceNotFound, SoundDeviceSource
    from fieldnotes.adapters.live import EchoGuard, LiveTurnSource
    from fieldnotes.adapters.stt_mlx_whisper import MlxWhisperTranscriber
    from fieldnotes.adapters.vad_silero import Segmenter, silero_prob_fn

    s = get_settings()
    try:
        audio = SoundDeviceSource(s.mic_device, s.client_device, s.sample_rate)
    except DeviceNotFound as e:
        typer.secho(f"{e}\nSee README: Audio setup.", fg="red", err=True)
        raise typer.Exit(1) from e
    transcriber = MlxWhisperTranscriber(s.whisper_model, s.language or None)
    logger.info("Loading Whisper (first run downloads the model)")
    transcriber.warm_up()

    def segmenter() -> Segmenter:
        return Segmenter(
            silero_prob_fn(s.sample_rate),
            s.sample_rate,
            s.vad_threshold,
            s.end_of_turn_ms,
            s.min_utterance_s,
            s.max_utterance_s,
        )

    return LiveTurnSource(
        audio,
        transcriber,
        {"me": segmenter(), "client": segmenter()},
        EchoGuard() if s.echo_guard else None,
    )


@app.command()
def devices() -> None:
    """List audio input devices."""
    import sounddevice as sd

    s = get_settings()
    default = sd.query_devices(kind="input")["name"]
    for d in sd.query_devices():
        if d["max_input_channels"] > 0:
            tags = []
            if d["name"] == default:
                tags.append("default mic")
            if s.client_device.lower() in d["name"].lower():
                tags.append("client channel")
            suffix = f"  <- {', '.join(tags)}" if tags else ""
            typer.echo(
                f"[{d['index']}] {d['name']}  ({d['max_input_channels']} in, "
                f"{int(d['default_samplerate'])} Hz){suffix}"
            )
    if not any(s.client_device.lower() in d["name"].lower() for d in sd.query_devices()):
        typer.secho(
            f"{s.client_device!r} not found: brew install blackhole-2ch, then see README.",
            fg="yellow",
        )


@app.command("check-audio")
def check_audio(seconds: Annotated[float, typer.Option()] = 15.0) -> None:
    """Show live levels for both channels. Speak, and play something in the call app."""
    import numpy as np
    import sounddevice as sd

    from fieldnotes.adapters.audio_sounddevice import DeviceNotFound, find_input

    s = get_settings()
    levels = {"me": -90.0, "client": -90.0}
    streams = []
    try:
        for speaker, name in (("me", s.mic_device), ("client", s.client_device)):
            device = find_input(name)

            def callback(indata, frames, t, status, speaker=speaker):
                rms = float(np.sqrt(np.mean(indata**2)) + 1e-9)
                levels[speaker] = max(20 * np.log10(rms), levels[speaker] - 3)

            stream = sd.InputStream(device=device["index"], channels=1, callback=callback)
            stream.start()
            streams.append(stream)
            typer.echo(f"{speaker:>6}: {device['name']}")
    except DeviceNotFound as e:
        typer.secho(str(e), fg="red", err=True)
        raise typer.Exit(1) from e

    def bar(db: float) -> str:
        filled = int(max(0, min(40, (db + 60) / 60 * 40)))
        return "#" * filled + "." * (40 - filled)

    end = time.time() + seconds
    try:
        while time.time() < end:
            typer.echo(
                f"\r  ME {bar(levels['me'])} {levels['me']:6.1f} dB   "
                f"CLIENT {bar(levels['client'])} {levels['client']:6.1f} dB",
                nl=False,
            )
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        for stream in streams:
            stream.stop()
            stream.close()
    typer.echo()


if __name__ == "__main__":
    app()
