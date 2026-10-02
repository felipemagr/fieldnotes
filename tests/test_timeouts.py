"""A stalled model must never freeze the board or the end of the call."""

import asyncio
import time

import pytest

from earpiece.adapters.fake_llm import FakeLLM
from earpiece.app import pipeline
from earpiece.app.brain import Brain
from earpiece.app.pipeline import ENDED, CallSession
from earpiece.domain.trigger import TurnTrigger
from earpiece.domain.turn import Turn

LONG = "our loan tape is an excel export that we cannot change because the vendor owns the format"


class HangingLLM(FakeLLM):
    """Answers the docs, then hangs on every call until `hang` is cleared."""

    def __init__(self):
        super().__init__(delay_s=0)
        self.hang = True

    async def send(self, message: str) -> str:
        if self.hang:
            await asyncio.sleep(3600)
        return await super().send(message)


class SilentSource:
    """Nobody speaks; ends when stopped, as a real source does."""

    def __init__(self):
        self.stopped = asyncio.Event()

    async def turns(self, on_activity):
        await self.stopped.wait()
        return
        yield  # pragma: no cover

    def stop(self):
        self.stopped.set()


def session(tmp_path, llm, **brain_kw):
    return CallSession(
        source=SilentSource(),
        brain=Brain(llm, **brain_kw),
        docs_loader=lambda: "docs",
        calls_dir=tmp_path,
        trigger=TurnTrigger(min_words=5, debounce_s=0),
    )


async def test_brain_call_times_out():
    brain = Brain(HangingLLM(), timeout_s=0.2)
    await brain.start("docs")
    with pytest.raises(TimeoutError):
        await brain.analyse([Turn(speaker="client", text=LONG, t0=0, t1=1)])


async def test_board_recovers_after_a_timeout(tmp_path):
    llm = HangingLLM()
    s = session(tmp_path, llm, timeout_s=0.2)
    await s.prepare()
    s._on_turn(Turn(speaker="client", text=LONG, t0=0, t1=1))
    await asyncio.sleep(0.4)
    assert "timed out" in s.error and not s._busy  # the Brain is free again
    llm.hang = False
    s._on_turn(Turn(speaker="client", text=LONG + " again", t0=1, t1=2))
    await asyncio.sleep(0.2)
    assert s.board.round == 1 and s.error is None


async def test_end_call_finishes_even_if_the_model_hangs(tmp_path):
    s = session(tmp_path, HangingLLM(), start_timeout_s=0.3, timeout_s=0.2, report_timeout_s=0.3)
    await s.prepare()
    s.give_consent()
    s._on_turn(Turn(speaker="client", text=LONG, t0=0, t1=1))
    t = time.monotonic()
    await s.end()
    assert time.monotonic() - t < 2
    assert s.state == ENDED
    assert "could not be written" in s.report
    assert s.report_path.exists()


async def test_turns_before_the_brain_is_ready_are_sent_once_it_is(tmp_path):
    llm = FakeLLM(delay_s=0)
    s = session(tmp_path, llm)
    s._on_turn(Turn(speaker="client", text=LONG, t0=0, t1=1))  # docs still loading
    await s.prepare()
    await asyncio.sleep(0.1)
    assert llm.calls == 1 and s.board.round == 1


async def test_slow_docs_do_not_block_forever(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "DOCS_GRACE_S", 0)
    s = CallSession(
        source=SilentSource(),
        brain=Brain(FakeLLM(delay_s=0)),
        docs_loader=lambda: time.sleep(1) or "docs",
        calls_dir=tmp_path,
        docs_timeout_s=0.2,
    )
    await s.prepare()
    assert not s.brain_ready.is_set() and "timed out" in s.error


async def test_restart_after_timeout_uses_its_own_budget():
    """A restart re-sends the docs on the start budget, not the per-call one."""

    class SlowStart(HangingLLM):
        async def start(self, system_prompt, context):
            await asyncio.sleep(0.3)  # longer than timeout_s, shorter than start_timeout_s

    llm = SlowStart()
    brain = Brain(llm, start_timeout_s=1, timeout_s=0.2)
    await brain.start("docs")
    with pytest.raises(TimeoutError):
        await brain.analyse([Turn(speaker="client", text=LONG, t0=0, t1=1)])
    llm.hang = False
    assert await brain.analyse([Turn(speaker="client", text=LONG, t0=0, t1=1)]) is not None


async def test_consent_after_end_is_ignored(tmp_path):
    s = session(tmp_path, FakeLLM(delay_s=0))
    await s.end()
    s.give_consent()
    assert s.state == ENDED and s.consent_at is None
