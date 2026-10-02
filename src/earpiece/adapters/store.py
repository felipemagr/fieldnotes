"""Turns of the current call, in memory, and on disk only when retention is on.

On-disk transcripts are deleted once older than `retention_days`. Audio is never stored.
"""

import logging
import time
from pathlib import Path

from earpiece.domain.turn import Turn

logger = logging.getLogger(__name__)

TRANSCRIPT_SUFFIX = ".transcript.jsonl"


class TranscriptStore:
    def __init__(self, path: Path | None = None):
        self.path = path
        self._turns: list[Turn] = []

    def append(self, turn: Turn) -> None:
        self._turns.append(turn)
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(turn.model_dump_json() + "\n")

    def all(self) -> list[Turn]:
        return list(self._turns)


def cleanup(directory: Path, retention_days: int, now: float | None = None) -> list[Path]:
    """Delete stored transcripts older than the retention window. Returns what was deleted."""
    if not directory.exists():
        return []
    cutoff = (now or time.time()) - retention_days * 86_400
    deleted = []
    for path in directory.glob(f"*{TRANSCRIPT_SUFFIX}"):
        if path.stat().st_mtime < cutoff:
            path.unlink()
            deleted.append(path)
    if deleted:
        logger.info(
            "Retention: deleted %d transcript(s) older than %d days", len(deleted), retention_days
        )
    return deleted
