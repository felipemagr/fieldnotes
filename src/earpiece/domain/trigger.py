"""When to ask the Brain.

A client turn of enough words, or one that asks something, arms the trigger. My own turns ride
along as context but never arm it. Turns that arrive while the Brain is busy wait and go together
in the next batch, so requests never pile up. Two requests never start closer than `debounce_s`.
"""

import re

from earpiece.domain.turn import Turn

QUESTION_START = re.compile(
    r"^(can|could|would|will|do|does|did|is|are|how|what|when|where|which|who|why|should)\b",
    re.IGNORECASE,
)


def is_question(text: str) -> bool:
    return "?" in text or bool(QUESTION_START.match(text.strip()))


class TurnTrigger:
    def __init__(self, min_words: int = 15, debounce_s: float = 2.0):
        self.min_words = min_words
        self.debounce_s = debounce_s
        self.pending: list[Turn] = []
        self.armed = False
        self.last_fired: float | None = None

    def qualifies(self, turn: Turn) -> bool:
        return turn.speaker == "client" and (turn.words >= self.min_words or is_question(turn.text))

    def add(self, turn: Turn) -> None:
        self.pending.append(turn)
        if self.qualifies(turn):
            self.armed = True

    def wait_s(self, now: float) -> float:
        """Seconds until the debounce allows the next request (0 when it does)."""
        if self.last_fired is None:
            return 0.0
        return max(0.0, self.last_fired + self.debounce_s - now)

    def take(self, now: float, busy: bool) -> list[Turn] | None:
        """The batch to send now, or None when it is not time yet."""
        if not self.armed or busy or self.wait_s(now) > 0:
            return None
        batch, self.pending, self.armed = self.pending, [], False
        self.last_fired = now
        return batch

    def drain(self) -> list[Turn]:
        """Everything still waiting, armed or not (used when the call ends)."""
        batch, self.pending, self.armed = self.pending, [], False
        return batch
