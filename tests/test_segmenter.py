import numpy as np

from fieldnotes.adapters.vad_silero import FRAME, Segmenter


def fake_prob(frame):
    return 1.0 if frame[0] > 0.5 else 0.0  # loud frames are speech


def audio(seconds_speech, seconds_silence):
    sr = 16_000
    return np.concatenate(
        [
            np.ones(int(sr * seconds_speech), np.float32),
            np.zeros(int(sr * seconds_silence), np.float32),
        ]
    )


def test_turn_ends_after_silence():
    seg = Segmenter(fake_prob, end_of_turn_ms=700, min_utterance_s=0.5)
    out = seg.feed(np.zeros(FRAME * 10, np.float32))
    out += seg.feed(audio(1.5, 0.5))
    assert out == []  # 500 ms of silence is not the end of a turn yet
    out = seg.feed(np.zeros(FRAME * 10, np.float32))
    assert len(out) == 1
    assert 1.4 < out[0].t1 - out[0].t0 < 2.0


def test_short_blips_are_dropped():
    seg = Segmenter(fake_prob, end_of_turn_ms=300, min_utterance_s=0.5)
    assert seg.feed(audio(0.2, 1.0)) == []


def test_long_monologue_is_cut():
    seg = Segmenter(fake_prob, max_utterance_s=2.0)
    out = seg.feed(audio(5.0, 0.0))
    assert len(out) == 2


def test_feed_handles_odd_chunk_sizes():
    seg = Segmenter(fake_prob, end_of_turn_ms=300)
    a = audio(1.0, 1.0)
    out = []
    for i in range(0, len(a), 333):
        out += seg.feed(a[i : i + 333])
    assert len(out) == 1


def test_pre_roll_does_not_count_as_speech():
    seg = Segmenter(fake_prob, end_of_turn_ms=300, min_utterance_s=0.5)
    out = seg.feed(np.zeros(FRAME * 10, np.float32))  # fills the pre-roll
    out += seg.feed(audio(0.35, 1.0))  # 0.35 s of speech + 0.19 s pre-roll: still a blip
    assert out == []


def test_flush_returns_open_speech():
    seg = Segmenter(fake_prob)
    seg.feed(audio(1.0, 0.0))
    u = seg.flush()
    assert u is not None and u.t1 - u.t0 > 0.95  # minus the part of a frame still buffered
    assert seg.flush() is None
