"""Live turns: audio capture, VAD per channel, transcription in a worker thread.

Capture never waits on Whisper: utterances queue for one worker thread (MLX runs one job at a
time) and come back as turns in the order they were spoken.
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable
from concurrent.futures import ThreadPoolExecutor

from earpiece.adapters.vad_silero import Segmenter, Utterance
from earpiece.domain.turn import Speaker, Turn
from earpiece.ports import AudioSource, Transcriber

logger = logging.getLogger(__name__)


class LiveTurnSource:
    def __init__(
        self,
        audio: AudioSource,
        transcriber: Transcriber,
        segmenters: dict[Speaker, Segmenter],
    ):
        self.audio = audio
        self.transcriber = transcriber
        self.segmenters = segmenters
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
