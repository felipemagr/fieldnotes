"""Speech to text on the Mac's GPU with mlx-whisper. The model loads once and is warmed up."""

import logging
import time

import numpy as np

logger = logging.getLogger(__name__)

# Whisper was trained on subtitled video: over noise it can emit the subtitle credits. These are
# never said on a call, so they are dropped by text. Everything else is judged by Whisper's own
# confidence per segment, not by a word list (people do say "okay" and "thank you").
SUBTITLE_ARTIFACTS = ("thanks for watching", "thank you for watching", "subtitles by", "amara.org")
NO_SPEECH_PROB = 0.6
LOW_LOGPROB = -1.0


def keep_segment(segment: dict) -> bool:
    """False for a segment Whisper itself thinks is silence it filled with words."""
    text = str(segment.get("text", "")).strip().lower()
    if not text or any(a in text for a in SUBTITLE_ARTIFACTS):
        return False
    silent = segment.get("no_speech_prob", 0.0) > NO_SPEECH_PROB
    unsure = segment.get("avg_logprob", 0.0) < LOW_LOGPROB
    return not (silent and unsure)


class MlxWhisperTranscriber:
    def __init__(self, model: str, language: str | None = "en"):
        import mlx_whisper

        self._mlx_whisper = mlx_whisper
        self.model = model
        self.language = language

    def warm_up(self) -> None:
        t = time.perf_counter()
        self.transcribe(np.zeros(16_000, dtype=np.float32), 16_000)
        logger.info("Whisper %s ready in %.1fs", self.model, time.perf_counter() - t)

    def transcribe(self, pcm: np.ndarray, sample_rate: int) -> str:
        if sample_rate != 16_000:
            raise ValueError("Whisper expects 16 kHz audio")
        result = self._mlx_whisper.transcribe(
            pcm.astype(np.float32),
            path_or_hf_repo=self.model,
            language=self.language,
            temperature=(0.0, 0.4),
            condition_on_previous_text=False,
            verbose=None,
        )
        segments = [seg for seg in result.get("segments", []) if keep_segment(seg)]
        return " ".join(" ".join(str(seg["text"]) for seg in segments).split())
