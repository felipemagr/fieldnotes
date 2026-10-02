"""One finished utterance of one speaker."""

from typing import Literal

from pydantic import BaseModel

Speaker = Literal["me", "client"]


class Turn(BaseModel):
    speaker: Speaker
    text: str
    t0: float  # seconds since the call started
    t1: float
    ended_at: float = 0.0  # wall clock when the speaker stopped, for latency

    @property
    def label(self) -> str:
        return "ME" if self.speaker == "me" else "CLIENT"

    @property
    def words(self) -> int:
        return len(self.text.split())

    def line(self) -> str:
        return f"{self.label}: {self.text}"
