"""Turns read from a transcript file and played back at speaking pace.

Lines look like `CLIENT: text` or `ME: text`. Blank lines and lines starting with `#` are
skipped. Each turn takes as long as it would to say it, then a short pause.
"""

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path

from earpiece.domain.turn import Speaker, Turn

WORDS_PER_SECOND = 2.6
PAUSE_S = 0.8
SPEAKERS: dict[str, Speaker] = {"ME": "me", "CLIENT": "client"}


def parse_transcript(text: str) -> list[tuple[Speaker, str]]:
    lines: list[tuple[Speaker, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        label, sep, said = line.partition(":")
        speaker = SPEAKERS.get(label.strip().upper())
        if not sep or speaker is None:
            raise ValueError(f"Expected 'ME: ...' or 'CLIENT: ...', got {line[:60]!r}")
        lines.append((speaker, said.strip()))
    return lines


class ReplaySource:
    def __init__(self, path: Path, speed: float = 1.0):
        self.lines = parse_transcript(path.read_text(encoding="utf-8"))
        self.speed = speed
        self._stopped = False

    async def turns(self, on_activity: Callable[[str], None]) -> AsyncIterator[Turn]:
        clock = 0.0
        for speaker, said in self.lines:
            if self._stopped:
                return
            duration = max(0.6, len(said.split()) / WORDS_PER_SECOND)
            await asyncio.sleep(duration / self.speed)
            on_activity("transcribing")
            yield Turn(
                speaker=speaker, text=said, t0=clock, t1=clock + duration, ended_at=time.time()
            )
            clock += duration + PAUSE_S
            await asyncio.sleep(PAUSE_S / self.speed)

    def stop(self) -> None:
        self._stopped = True
