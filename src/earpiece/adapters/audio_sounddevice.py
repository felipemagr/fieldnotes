"""Two input streams: my mic and the call's audio through BlackHole.

Speaker identity comes from the device, so no diarization is needed. Each device is opened at its
own native rate and resampled to 16 kHz mono here. Nothing is ever written to disk.
"""

import asyncio
import logging
from collections.abc import AsyncIterator

import numpy as np
import sounddevice as sd

from earpiece.domain.turn import Speaker

logger = logging.getLogger(__name__)


class DeviceNotFound(RuntimeError):
    pass


def input_devices() -> list[dict]:
    return [d for d in sd.query_devices() if d["max_input_channels"] > 0]


def find_input(name: str | None) -> dict:
    """The input device whose name contains `name`, or the default input when None."""
    if name is None:
        return sd.query_devices(kind="input")
    matches = [d for d in input_devices() if name.lower() in d["name"].lower()]
    if not matches:
        names = ", ".join(d["name"] for d in input_devices()) or "none"
        raise DeviceNotFound(f"No input device matching {name!r}. Inputs: {names}")
    return matches[0]


def resample(pcm: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst:
        return pcm
    if src % dst == 0:  # 48k -> 16k: average each group of samples (a cheap low-pass)
        factor = src // dst
        whole = len(pcm) // factor * factor
        return pcm[:whole].reshape(-1, factor).mean(axis=1).astype(np.float32)
    n = int(round(len(pcm) * dst / src))
    x = np.linspace(0, len(pcm) - 1, n)
    return np.interp(x, np.arange(len(pcm)), pcm).astype(np.float32)


class SoundDeviceSource:
    def __init__(self, mic: str | None, client: str, sample_rate: int = 16_000):
        self.sample_rate = sample_rate
        self.devices: dict[Speaker, dict] = {"me": find_input(mic), "client": find_input(client)}
        self._streams: list[sd.InputStream] = []
        self._queue: asyncio.Queue[tuple[Speaker, np.ndarray] | None] | None = None

    def _open(self, speaker: Speaker, device: dict, loop: asyncio.AbstractEventLoop) -> None:
        native = int(device["default_samplerate"])

        def callback(indata, _frames, _time, status):
            if status:
                logger.debug("%s audio status: %s", speaker, status)
            mono = indata.mean(axis=1) if indata.shape[1] > 1 else indata[:, 0]
            pcm = resample(mono.astype(np.float32), native, self.sample_rate)
            loop.call_soon_threadsafe(self._queue.put_nowait, (speaker, pcm))

        stream = sd.InputStream(
            device=device["index"],
            channels=1,
            samplerate=native,
            dtype="float32",
            blocksize=int(native * 0.032),
            callback=callback,
        )
        stream.start()
        self._streams.append(stream)
        logger.info("Capturing %s from %r at %d Hz", speaker, device["name"], native)

    async def chunks(self) -> AsyncIterator[tuple[Speaker, np.ndarray]]:
        loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue()
        for speaker, device in self.devices.items():
            self._open(speaker, device, loop)
        try:
            while (item := await self._queue.get()) is not None:
                yield item
        finally:
            self.stop()

    def stop(self) -> None:
        """Close the streams and end `chunks()`. Call it from the event loop thread."""
        if self._streams and self._queue is not None:
            self._queue.put_nowait(None)
        for stream in self._streams:
            stream.stop()
            stream.close()
        self._streams = []
