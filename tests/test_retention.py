import os
import time

from earpiece.adapters.store import TRANSCRIPT_SUFFIX, TranscriptStore, cleanup
from earpiece.domain.turn import Turn


def test_cleanup_deletes_only_old_transcripts(tmp_path):
    old = tmp_path / f"old{TRANSCRIPT_SUFFIX}"
    new = tmp_path / f"new{TRANSCRIPT_SUFFIX}"
    report = tmp_path / "2026-01-01-call.md"
    for p in (old, new, report):
        p.write_text("x")
    ten_days_ago = time.time() - 10 * 86_400
    os.utime(old, (ten_days_ago, ten_days_ago))
    os.utime(report, (ten_days_ago, ten_days_ago))
    assert cleanup(tmp_path, retention_days=7) == [old]
    assert not old.exists() and new.exists() and report.exists()


def test_cleanup_missing_dir(tmp_path):
    assert cleanup(tmp_path / "nope", 7) == []


def test_store_writes_only_when_enabled(tmp_path):
    turn = Turn(speaker="client", text="hi", t0=0, t1=1)
    memory = TranscriptStore()
    memory.append(turn)
    assert memory.all() == [turn] and list(tmp_path.iterdir()) == []
    disk = TranscriptStore(tmp_path / f"c{TRANSCRIPT_SUFFIX}")
    disk.append(turn)
    assert '"text":"hi"' in (tmp_path / f"c{TRANSCRIPT_SUFFIX}").read_text()
