"""Live turns: audio capture, VAD per channel, transcription in a worker thread.

Capture never waits on Whisper: utterances queue for one worker thread (MLX runs one job at a
time) and come back as turns in the order they were spoken.
"""

import asyncio
import logging
import time
from collections import deque
from collections.abc import AsyncIterator, Callable
from concurrent.futures import ThreadPoolExecutor

from fieldnotes.adapters.vad_silero import Segmenter, Utterance
from fieldnotes.domain.turn import Speaker, Turn
from fieldnotes.ports import AudioSource, Transcriber

logger = logging.getLogger(__name__)


class EchoGuard:
    """Tells your speech from the client's voice leaking into your mic.

    On speakers, the mic hears the client too, and that would show up as ME. Speech on your
    channel that mostly overlaps in time with the client's is that echo. Both channels share one
    clock (seconds since capture started), so spans compare directly. The cost: a short
    interjection while the client talks is dropped as well. Headphones avoid both.
    """

    def __init__(self, overlap: float = 0.6, keep_s: float = 60.0):
        self.overlap = overlap
        self.keep_s = keep_s
        self.client_spans: deque[tuple[float, float]] = deque()

    def client_spoke(self, t0: float, t1: float) -> None:
        self.client_spans.append((t0, t1))
        while self.client_spans and self.client_spans[0][1] < t1 - self.keep_s:
            self.client_spans.popleft()

    def is_echo(self, t0: float, t1: float, client_open_since: float | None = None) -> bool:
        spans = list(self.client_spans)
        if client_open_since is not None:  # the client is still talking
            spans.append((client_open_since, t1))
        covered = sum(max(0.0, min(t1, b) - max(t0, a)) for a, b in spans)
        return covered >= self.overlap * (t1 - t0)


class LiveTurnSource:
    def __init__(
        self,
        audio: AudioSource,
        transcriber: Transcriber,
        segmenters: dict[Speaker, Segmenter],
        echo_guard: EchoGuard | None = None,
    ):
        self.audio = audio
        self.transcriber = transcriber
        self.segmenters = segmenters
        self.echo_guard = echo_guard
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="whisper")
        self._stopped = False

    def _transcribe(self, speaker: Speaker, u: Utterance, vad_end: float) -> Turn | None:
        try:
            text = self.transcriber.transcribe(u.pcm, self.audio.sample_rate)
        except Exception:  # one bad utterance must not end the call
            logger.exception("Transcription failed for a %s turn", speaker)
            return None
        logger.info(
            "%s turn %.1fs of audio: VAD end -> text in %.2fs",
            speaker,
            u.t1 - u.t0,
            time.time() - vad_end,
        )
        if not text:
            return None
        return Turn(speaker=speaker, text=text, t0=u.t0, t1=u.t1, ended_at=vad_end)

    async def turns(self, on_activity: Callable[[str], None]) -> AsyncIterator[Turn]:
        loop = asyncio.get_running_loop()
        pending: asyncio.Queue[asyncio.Future | None] = asyncio.Queue()

        def submit(speaker: Speaker, u: Utterance) -> None:
            guard = self.echo_guard
            if guard is not None:
                if speaker == "client":
                    guard.client_spoke(u.t0, u.t1)
                elif guard.is_echo(u.t0, u.t1, self.segmenters["client"].open_since):
                    logger.info("Dropped %.1fs on the mic: the client's voice (echo)", u.t1 - u.t0)
                    return
            on_activity("transcribing")
            future = loop.run_in_executor(self._worker, self._transcribe, speaker, u, time.time())
            pending.put_nowait(future)

        async def capture() -> None:
            try:
                async for speaker, pcm in self.audio.chunks():
                    if self._stopped:
                        break
                    for u in self.segmenters[speaker].feed(pcm):
                        submit(speaker, u)
                # Capture ended (call over): speech still open becomes a last turn.
                for speaker, segmenter in self.segmenters.items():
                    if (u := segmenter.flush()) is not None:
                        submit(speaker, u)
            finally:
                pending.put_nowait(None)

        task = asyncio.create_task(capture())
        try:
            while (future := await pending.get()) is not None:
                turn = await future
                if turn is None:
                    on_activity("idle")
                else:
                    yield turn
            (failure,) = await asyncio.gather(task, return_exceptions=True)
            if isinstance(failure, Exception):
                raise failure  # capture failed: let the panel show it
        finally:
            task.cancel()
            self.audio.stop()

    def stop(self) -> None:
        self._stopped = True
        self.audio.stop()
