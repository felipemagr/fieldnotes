"""Test doubles: a model with a canned answer and a turn source that reads a transcript."""

import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable

from fieldnotes.app.brain import REPORT_MARKER
from fieldnotes.domain.turn import Speaker, Turn

ANSWER = {
    "client_needs": ["Excel tape, format fixed by vendor"],
    "fence_mapping": [
        {
            "need": "Excel loan tape",
            "approach": "Our file adapter maps columns, declares the book",
            "endpoint": "POST /v2/declarations",
            "doc_ref": "https://docs.fence.finance/#declaration-flow",
        }
    ],
    "questions_to_ask": ["Can you send a sample file?"],
    "route_to_ops": ["Higher advance rate for clean data?"],
    "risks": ["Day and month swapped on parse"],
}


class FakeLLM:
    model = "fake"

    def __init__(self, delay_s: float = 0.0):
        self.delay_s = delay_s
        self.calls = 0

    async def start(self, system_prompt: str, context: str) -> None:
        pass

    async def send(self, message: str) -> str:
        await asyncio.sleep(self.delay_s)
        if REPORT_MARKER in message:
            return "## Summary\n- Canned report."
        self.calls += 1
        return "Here you go:\n```json\n" + json.dumps(ANSWER) + "\n```"  # wrapped, as models do

    async def close(self) -> None:
        pass


class TextSource:
    """Turns from `ME: ...` / `CLIENT: ...` lines, a short pause apart."""

    def __init__(self, text: str, pause_s: float = 0.02):
        self.lines: list[tuple[Speaker, str]] = []
        for line in text.strip().splitlines():
            label, _, said = line.partition(":")
            self.lines.append(("me" if label.strip() == "ME" else "client", said.strip()))
        self.pause_s = pause_s
        self._stopped = False

    async def turns(self, on_activity: Callable[[str], None]) -> AsyncIterator[Turn]:
        for n, (speaker, said) in enumerate(self.lines):
            if self._stopped:
                return
            await asyncio.sleep(self.pause_s)
            yield Turn(speaker=speaker, text=said, t0=n, t1=n + 1, ended_at=time.time())

    def stop(self) -> None:
        self._stopped = True
