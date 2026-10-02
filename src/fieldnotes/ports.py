"""The seams. Business logic talks to these, never to audio devices, Whisper, Claude or HTTP."""

from collections.abc import AsyncIterator, Callable
from typing import Protocol

import numpy as np

from fieldnotes.domain.turn import Speaker, Turn


class AudioSource(Protocol):
    """Raw audio, one channel per speaker, already at the target sample rate."""

    sample_rate: int

    def chunks(self) -> AsyncIterator[tuple[Speaker, np.ndarray]]: ...

    def stop(self) -> None: ...


class Transcriber(Protocol):
    def transcribe(self, pcm: np.ndarray, sample_rate: int) -> str: ...


class TurnSource(Protocol):
    """Finished turns. Live audio (capture + VAD + transcription) and replay both are one.

    `on_activity` hears "transcribing" while speech is being turned into text.
    """

    def turns(self, on_activity: Callable[[str], None]) -> AsyncIterator[Turn]: ...

    def stop(self) -> None: ...


class LLM(Protocol):
    """One conversation per call: the context goes in once, then only new messages."""

    model: str

    async def start(self, system_prompt: str, context: str) -> None: ...

    async def send(self, message: str) -> str: ...

    async def close(self) -> None: ...
