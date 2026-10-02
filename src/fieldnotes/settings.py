"""Runtime settings, read from the environment (prefix `FIELDNOTES_`) or `.env`."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FIELDNOTES_", env_file=".env", extra="ignore")

    # Brain
    model: str = "haiku"
    docs_url: str = "https://docs.fence.finance/"
    docs_dir: Path = Path("data/docs")
    docs_ttl_days: int = 7
    docs_max_pages: int = 40
    docs_delay_s: float = 0.5
    docs_warn_tokens: int = 120_000
    docs_timeout_s: float = 60.0  # whole crawl, not per page

    # Time limits for the model. A stalled call fails instead of freezing the board.
    llm_start_timeout_s: float = 60.0
    llm_timeout_s: float = 30.0
    report_timeout_s: float = 120.0

    # Panel
    host: str = "127.0.0.1"
    port: int = 8765

    # Audio: the mic is the default input unless named; the client comes through BlackHole.
    mic_device: str | None = None
    client_device: str = "BlackHole 2ch"
    sample_rate: int = 16_000
    vad_threshold: float = 0.5
    end_of_turn_ms: int = 700
    min_utterance_s: float = 0.5
    max_utterance_s: float = 25.0

    # Speech to text
    whisper_model: str = "mlx-community/whisper-large-v3-turbo"
    language: str = "en"

    # Trigger
    trigger_min_words: int = 15
    debounce_s: float = 2.0

    # Records. Audio is never written anywhere.
    calls_dir: Path = Path("calls")
    keep_transcripts: bool = False
    retention_days: int = 7


@lru_cache
def get_settings() -> Settings:
    return Settings()
