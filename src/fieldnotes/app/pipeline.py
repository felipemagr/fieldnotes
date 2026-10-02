"""One call, wired end to end: turns in, Brain in batches, board out, report at the end."""

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from fieldnotes.adapters.cache import slug
from fieldnotes.adapters.store import TRANSCRIPT_SUFFIX, TranscriptStore
from fieldnotes.app.brain import Brain
from fieldnotes.domain.board import Board
from fieldnotes.domain.trigger import TurnTrigger
from fieldnotes.domain.turn import Turn
from fieldnotes.ports import TurnSource

logger = logging.getLogger(__name__)

# States shown in the top bar.
STARTING = "starting"
LISTENING = "listening"
TRANSCRIBING = "transcribing"
THINKING = "thinking"
WRITING_REPORT = "writing report"
ENDED = "ended"


# The crawl checks its own deadline between pages; give it room to finish the page it is on.
DOCS_GRACE_S = 15.0
# How long ending a call waits for speech already captured to be transcribed.
DRAIN_S = 10.0


class Bus:
    """Fan-out of events to every open panel."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict]] = set()

    def subscribe(self) -> asyncio.Queue[dict]:
        queue: asyncio.Queue[dict] = asyncio.Queue()
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict]) -> None:
        self._subscribers.discard(queue)

    def publish(self, event: dict) -> None:
        for queue in self._subscribers:
            queue.put_nowait(event)


class CallSession:
    def __init__(
        self,
        source: TurnSource,
        brain: Brain,
        docs_loader: Callable[[], str],
        calls_dir: Path,
        name: str = "call",
        keep_transcripts: bool = False,
        trigger: TurnTrigger | None = None,
        docs_timeout_s: float = 60.0,
    ):
        self.source = source
        self.brain = brain
        self.docs_loader = docs_loader
        self.docs_timeout_s = docs_timeout_s
        self.calls_dir = calls_dir
        self.name = name
        self.trigger = trigger or TurnTrigger()
        self.board = Board()
        self.bus = Bus()
        stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
        self.slug = slug(name) or "call"
        self.call_id = f"{stamp}-{self.slug}"
        self.store = TranscriptStore(
            calls_dir / f"{self.call_id}{TRANSCRIPT_SUFFIX}" if keep_transcripts else None
        )
        self.state = STARTING
        self.error: str | None = None
        self.brain_ready = asyncio.Event()
        self.started_at: datetime | None = None
        self.report: str | None = None
        self.report_path: Path | None = None
        self.last_latency_s: float | None = None
        self._busy = False
        self._tasks: set[asyncio.Task] = set()
        self._listen_task: asyncio.Task | None = None
        self._prepare_task: asyncio.Task | None = None
        self._analyse_task: asyncio.Task | None = None
        self._end_task: asyncio.Task | None = None
        self._timer: asyncio.TimerHandle | None = None

    # ---- events -------------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        return {
            "type": "snapshot",
            "state": self.state,
            "error": self.error,
            "model": self.brain.model,
            "brain_ready": self.brain_ready.is_set(),
            "latency_s": self.last_latency_s,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "transcript": [t.model_dump() for t in self.store.all()],
            "board": self.board.snapshot(),
            "report": self.report,
            "report_path": str(self.report_path) if self.report_path else None,
        }

    def _set_state(self, state: str) -> None:
        if self.state == state:
            return
        self.state = state
        self.bus.publish({"type": "state", "state": state, "latency_s": self.last_latency_s})

    def _set_error(self, message: str | None) -> None:
        self.error = message
        self.bus.publish({"type": "error", "error": message})

    def spawn(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    # ---- lifecycle ----------------------------------------------------------------------

    def start_preparing(self) -> None:
        self._prepare_task = self.spawn(self.prepare())

    async def prepare(self) -> None:
        """Load the docs into the Brain. Turns that arrive meanwhile wait for it."""
        try:
            docs = await asyncio.wait_for(
                asyncio.to_thread(self.docs_loader), self.docs_timeout_s + DOCS_GRACE_S
            )
            await self.brain.start(docs)
        except TimeoutError:
            logger.error("Brain did not start in time")
            self._set_error("Brain failed to start: timed out (docs or model)")
            return
        except Exception as e:  # shown in the panel; the call can still be transcribed
            logger.exception("Brain failed to start")
            self._set_error(f"Brain failed to start: {e}")
            return
        self.brain_ready.set()
        self._kick()  # turns may have armed the trigger while the docs were loading

    def start_listening(self) -> None:
        if self.state != STARTING:
            return
        self.started_at = datetime.now().astimezone()
        logger.info("Listening since %s", self.started_at.isoformat())
        self._write_record()
        self._set_state(LISTENING)
        self._listen_task = self.spawn(self._listen())

    async def _listen(self) -> None:
        try:
            async for turn in self.source.turns(self._on_activity):
                self._on_turn(turn)
        except Exception as e:
            logger.exception("Turn source failed")
            self._set_error(f"Audio or transcription failed: {e}")

    def _on_activity(self, activity: str) -> None:
        """`transcribing` when speech went to Whisper, `idle` when it came back with nothing."""
        if activity == "transcribing" and self.state == LISTENING:
            self._set_state(TRANSCRIBING)
        elif activity == "idle" and self.state == TRANSCRIBING:
            self._set_state(LISTENING)

    def _on_turn(self, turn: Turn) -> None:
        self.store.append(turn)
        self.bus.publish({"type": "turn", "turn": turn.model_dump()})
        if self.state == TRANSCRIBING:
            self._set_state(LISTENING)
        self.trigger.add(turn)
        self._kick()

    def _kick(self) -> None:
        """Send the waiting batch if the trigger says so, else check again after the debounce."""
        if self.state in (WRITING_REPORT, ENDED) or not self.brain_ready.is_set():
            return
        now = time.monotonic()
        batch = self.trigger.take(now, self._busy)
        if batch:
            self._busy = True
            self._analyse_task = self.spawn(self._analyse(batch))
        elif self.trigger.armed and not self._busy and self._timer is None:
            wait = self.trigger.wait_s(now)
            self._timer = asyncio.get_running_loop().call_later(wait, self._on_timer)

    def _on_timer(self) -> None:
        self._timer = None
        self._kick()

    async def _analyse(self, batch: list[Turn]) -> None:
        if self.state in (LISTENING, TRANSCRIBING):
            self._set_state(THINKING)
        try:
            suggestion = await self.brain.analyse(batch, self.board.brief())
            if suggestion is not None:
                changed = self.board.merge(suggestion)
                ended = max((t.ended_at for t in batch if t.speaker == "client"), default=0)
                if ended:
                    self.last_latency_s = time.time() - ended
                    logger.info(
                        "Client stopped -> suggestions on screen: %.2fs", self.last_latency_s
                    )
                self.bus.publish(
                    {
                        "type": "board",
                        "board": self.board.snapshot(),
                        "changed": [i.id for i in changed],
                        "latency_s": self.last_latency_s,
                    }
                )
            if self.error and self.error.startswith("Brain"):
                self._set_error(None)
        except TimeoutError:
            logger.error("Brain call timed out, batch skipped")
            self._set_error("Brain call timed out; the next update reconnects")
        except Exception as e:
            logger.exception("Brain call failed")
            self._set_error(f"Brain call failed: {e}")
        finally:
            self._busy = False
            if self.state == THINKING:
                self._set_state(LISTENING)
            self._kick()

    # ---- the panel's actions ------------------------------------------------------------

    def pin(self, item_id: int, pinned: bool) -> None:
        self.board.pin(item_id, pinned)
        self.bus.publish({"type": "board", "board": self.board.snapshot(), "changed": []})

    def dismiss(self, item_id: int) -> None:
        self.board.dismiss(item_id)
        self.bus.publish({"type": "board", "board": self.board.snapshot(), "changed": []})

    def request_end(self) -> None:
        if self._end_task is None:
            self._end_task = self.spawn(self.end())

    async def end(self) -> None:
        """Stop listening, ask for the report, save it. Nothing is sent to anyone."""
        if self.state in (WRITING_REPORT, ENDED):
            return
        # First, so no new update starts while the call winds down.
        self._set_state(WRITING_REPORT)
        if self._timer:
            self._timer.cancel()
            self._timer = None
        # Stop capture, but let speech already captured finish transcribing: the last
        # question often comes right before End is clicked.
        self.source.stop()
        if self._listen_task is not None and not self._listen_task.done():
            await asyncio.wait({self._listen_task}, timeout=DRAIN_S)
            self._listen_task.cancel()
        # The Brain may still be loading, or answering the last batch: wait, but not forever.
        for task, limit in (
            (self._prepare_task, self.docs_timeout_s + DOCS_GRACE_S + self.brain.start_timeout_s),
            (self._analyse_task, self.brain.max_analyse_s + 2),
        ):
            if task is not None and not task.done():
                await asyncio.wait({task}, timeout=limit)
                task.cancel()
        self.trigger.drain()
        try:
            if not self.brain_ready.is_set():
                raise RuntimeError("the Brain never started")
            body = await self.brain.report(self.store.all(), self.board.as_text())
        except Exception as e:
            logger.exception("Report failed")
            body = f"_The report could not be written: {e}_\n\n## Board\n\n{self.board.as_text()}"
        self.report = self._header() + body + "\n"
        self.report_path = self._save_report(self.report)
        self._write_record()
        self.bus.publish(
            {"type": "report", "report": self.report, "report_path": str(self.report_path)}
        )
        self._set_state(ENDED)

    async def close(self) -> None:
        """Server shutdown. A report being written gets a few seconds to land."""
        self.source.stop()
        if self._end_task is not None and not self._end_task.done():
            await asyncio.wait({self._end_task}, timeout=10)
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.wait(set(self._tasks), timeout=5)
        with contextlib.suppress(Exception):
            await self.brain.close()

    # ---- records ------------------------------------------------------------------------

    def _header(self) -> str:
        started = self.started_at.strftime("%Y-%m-%d %H:%M %Z") if self.started_at else "never"
        return (
            f"# Call report: {self.name}\n\n"
            f"- Date: {datetime.now():%Y-%m-%d %H:%M}\n"
            f"- Started: {started}\n"
            f"- Model: {self.brain.model}\n\n"
        )

    def _save_report(self, text: str) -> Path:
        self.calls_dir.mkdir(parents=True, exist_ok=True)
        path = self.calls_dir / f"{datetime.now():%Y-%m-%d}-{self.slug}.md"
        n = 2
        while path.exists():
            path = path.with_name(f"{datetime.now():%Y-%m-%d}-{self.slug}-{n}.md")
            n += 1
        path.write_text(text, encoding="utf-8")
        logger.info("Report saved to %s", path)
        return path

    def _write_record(self) -> None:
        """The call record: when it started, no transcript content."""
        self.calls_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "call_id": self.call_id,
            "name": self.name,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "model": self.brain.model,
            "report": str(self.report_path) if self.report_path else None,
            "transcript_kept": self.store.path is not None,
            "audio_stored": False,
        }
        path = self.calls_dir / f"{self.call_id}.call.json"
        path.write_text(json.dumps(record, indent=2), encoding="utf-8")
