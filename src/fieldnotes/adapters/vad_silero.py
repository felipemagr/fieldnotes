"""Cut one channel of audio into utterances with Silero VAD.

The model scores 512-sample frames at 16 kHz. A turn ends after `end_of_turn_ms` of silence;
anything shorter than `min_utterance_s` is dropped (coughs, "mm"); a monologue is cut at
`max_utterance_s` so the panel keeps up.
"""

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

FRAME = 512
PRE_ROLL_FRAMES = 6  # ~190 ms kept before speech starts, so first syllables survive


@dataclass
class Utterance:
    pcm: np.ndarray
    t0: float  # seconds since this channel started
    t1: float


def silero_prob_fn(sample_rate: int = 16_000) -> Callable[[np.ndarray], float]:
    """A speech probability per frame from a fresh Silero model (it keeps state per channel)."""
    import torch
    from silero_vad import load_silero_vad

    model = load_silero_vad()

    def prob(frame: np.ndarray) -> float:
        with torch.no_grad():
            return float(model(torch.from_numpy(frame), sample_rate).item())

    return prob


class Segmenter:
    def __init__(
        self,
        prob: Callable[[np.ndarray], float],
        sample_rate: int = 16_000,
        threshold: float = 0.5,
        end_of_turn_ms: int = 700,
        min_utterance_s: float = 0.5,
        max_utterance_s: float = 25.0,
    ):
        self.prob = prob
        self.sr = sample_rate
        self.threshold = threshold
        self.end_frames = max(1, round(end_of_turn_ms / 1000 * sample_rate / FRAME))
        self.min_samples = int(min_utterance_s * sample_rate)
        self.max_samples = int(max_utterance_s * sample_rate)
        self._carry = np.zeros(0, dtype=np.float32)
        self._pre: deque[np.ndarray] = deque(maxlen=PRE_ROLL_FRAMES)
        self._speech: list[np.ndarray] = []
        self._silent = 0
        self._frames_seen = 0
        self._start_frame = 0
        self._pre_frames = 0

    @property
    def open_since(self) -> float | None:
        """When the speech still in progress started (seconds), or None in silence."""
        return self._start_frame * FRAME / self.sr if self._speech else None

    def feed(self, pcm: np.ndarray) -> list[Utterance]:
        """Add audio; return the utterances it finished."""
        audio = np.concatenate([self._carry, pcm.astype(np.float32, copy=False)])
        whole = len(audio) // FRAME * FRAME
        self._carry = audio[whole:]
        done = []
        for frame in audio[:whole].reshape(-1, FRAME):
            if (u := self._step(frame)) is not None:
                done.append(u)
        return done

    def _step(self, frame: np.ndarray) -> Utterance | None:
        self._frames_seen += 1
        p = self.prob(frame)
        if not self._speech:
            if p >= self.threshold:
                self._start_frame = self._frames_seen - len(self._pre) - 1
                self._pre_frames = len(self._pre)
                self._speech = [*self._pre, frame]
                self._silent = 0
            else:
                self._pre.append(frame)
            return None
        self._speech.append(frame)
        # Hysteresis, as Silero's own iterator: speech ends a little below the threshold.
        self._silent = self._silent + 1 if p < self.threshold - 0.15 else 0
        if self._silent >= self.end_frames:
            return self._finish(trim=self._silent)
        if len(self._speech) * FRAME >= self.max_samples:
            return self._finish(trim=0)
        return None

    def _finish(self, trim: int) -> Utterance | None:
        frames = self._speech[: len(self._speech) - max(0, trim - 3)]  # keep ~100 ms of tail
        self._speech, self._silent = [], 0
        self._pre.clear()
        pcm = np.concatenate(frames)
        voiced = len(frames) - self._pre_frames - min(trim, 3)  # pre-roll is not speech
        if voiced * FRAME < self.min_samples:
            return None
        t0 = self._start_frame * FRAME / self.sr
        return Utterance(pcm=pcm, t0=t0, t1=t0 + len(pcm) / self.sr)

    def flush(self) -> Utterance | None:
        """Whatever speech is still open (used when capture stops)."""
        return self._finish(trim=self._silent) if self._speech else None
