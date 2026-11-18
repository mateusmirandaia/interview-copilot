"""Captures the Windows OUTPUT audio (WASAPI loopback): what the interviewer says, never the mic.

Delivers PCM16 mono 16 kHz chunks, each with the ``time.perf_counter()`` at which the chunk
finished being captured. That timestamp is used to measure the real latency
"end of speech -> answer on screen". ``pyaudiowpatch`` is imported lazily, so this module
imports on any OS.
"""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

TARGET_RATE = 16000


@dataclass
class AudioChunk:
    """A block of audio ready for speech-to-text."""

    pcm16: bytes   # mono, 16 kHz, int16 little-endian
    t_end: float   # perf_counter at the end of the block
    rms: float     # energy (0-1), for the VAD and the level meter


class Resampler:
    """Downmix to mono + resample to 16 kHz, without scipy. Keeps leftovers between calls."""

    def __init__(self, in_rate: int, channels: int):
        self.in_rate = int(in_rate)
        self.channels = int(channels)
        self._carry = np.zeros(0, dtype=np.float32)

    def process(self, data: np.ndarray) -> np.ndarray:
        """``data``: interleaved float32 in [-1, 1]. Returns mono float32 at 16 kHz."""
        if self.channels > 1:
            data = data.reshape(-1, self.channels).mean(axis=1)
        data = np.concatenate([self._carry, data.astype(np.float32)])
        if self.in_rate == TARGET_RATE:
            self._carry = np.zeros(0, dtype=np.float32)
            return data
        if self.in_rate % TARGET_RATE == 0:
            # 48k/32k -> 16k: block average (simple low-pass) + decimation
            k = self.in_rate // TARGET_RATE
            n = (len(data) // k) * k
            self._carry = data[n:]
            return data[:n].reshape(-1, k).mean(axis=1)
        # other rates (44.1k...): linear interpolation
        ratio = TARGET_RATE / self.in_rate
        n_out = int(len(data) * ratio)
        if n_out == 0:
            self._carry = data
            return np.zeros(0, dtype=np.float32)
        used = int(n_out / ratio)
        x_old = np.arange(used)
        x_new = np.linspace(0, used - 1, n_out)
        out = np.interp(x_new, x_old, data[:used]).astype(np.float32)
        self._carry = data[used:]
        return out


def float_to_pcm16(x: np.ndarray) -> bytes:
    """float32 [-1, 1] -> int16 little-endian bytes."""
    return (np.clip(x, -1.0, 1.0) * 32767).astype("<i2").tobytes()


def _pyaudio() -> Any:
    try:
        import pyaudiowpatch
    except ImportError as e:
        raise RuntimeError("pyaudiowpatch is not installed: audio capture needs Windows "
                           "(pip install pyaudiowpatch).") from e
    return pyaudiowpatch


def default_loopback_device() -> dict[str, Any] | None:
    """The loopback device of the default Windows output (None if not found)."""
    pyaudio = _pyaudio()
    p = pyaudio.PyAudio()
    try:
        return p.get_default_wasapi_loopback()
    except (OSError, AttributeError):
        return None
    finally:
        p.terminate()


def list_loopback_devices() -> list[dict[str, Any]]:
    """Every WASAPI loopback device (outputs that can be captured)."""
    pyaudio = _pyaudio()
    p = pyaudio.PyAudio()
    try:
        return list(p.get_loopback_device_info_generator())
    finally:
        p.terminate()


class LoopbackCapture:
    """Reads the WASAPI loopback in a thread and calls ``on_chunk(AudioChunk)``."""

    def __init__(self, on_chunk: Callable[[AudioChunk], None], device_name: str = "", chunk_ms: int = 50):
        self.on_chunk = on_chunk
        self.device_name = device_name.strip().lower()
        self.chunk_ms = chunk_ms
        self.device_label = "?"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._q: queue.Queue[tuple[bytes, float]] = queue.Queue(maxsize=400)
        self._emit_lock = threading.Lock()
        self._rs: Resampler | None = None
        self._last_real = 0.0
        self._last_synth = 0.0
        self.error: str | None = None

    # ---- device -------------------------------------------------------------------------
    def _pick_device(self, p: Any, pyaudio: Any) -> dict[str, Any]:
        if self.device_name:
            for d in p.get_loopback_device_info_generator():
                if self.device_name in d["name"].lower():
                    return d
            raise RuntimeError(f"Loopback device '{self.device_name}' not found. "
                               "Run: python -m interview_copilot devices")
        try:
            return p.get_default_wasapi_loopback()
        except (OSError, AttributeError):
            wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
            speaker = p.get_device_info_by_index(wasapi["defaultOutputDevice"])
            for d in p.get_loopback_device_info_generator():
                if speaker["name"] in d["name"]:
                    return d
        raise RuntimeError("No WASAPI loopback device found.")

    # ---- lifecycle ----------------------------------------------------------------------
    def start(self) -> None:
        """Start the capture and dispatch threads."""
        self._thread = threading.Thread(target=self._run_safe, name="capture", daemon=True)
        self._thread.start()
        threading.Thread(target=self._dispatch, name="capture-dispatch", daemon=True).start()

    def stop(self) -> None:
        """Stop capturing."""
        self._stop.set()

    def _run_safe(self) -> None:
        try:
            self._run()
        except Exception as e:  # noqa: BLE001 - surfaced through device_label/error
            self.error = str(e)
            self.device_label = f"ERROR: {e}"

    def _run(self) -> None:
        pyaudio = _pyaudio()
        p = pyaudio.PyAudio()
        dev = self._pick_device(p, pyaudio)
        rate = int(dev["defaultSampleRate"])
        ch = int(dev["maxInputChannels"]) or 2
        self.device_label = f"{dev['name']} ({rate} Hz, {ch} ch)"
        frames = int(rate * self.chunk_ms / 1000)
        self._rs = Resampler(rate, ch)
        self._last_real = time.perf_counter()

        def callback(in_data, frame_count, time_info, status):
            t = time.perf_counter()
            self._last_real = t
            try:
                self._q.put_nowait((in_data, t))
            except queue.Full:
                pass   # drop if speech-to-text stalls: never block the audio callback
            return (None, pyaudio.paContinue)

        stream = p.open(format=pyaudio.paFloat32, channels=ch, rate=rate, input=True,
                        input_device_index=dev["index"], frames_per_buffer=frames,
                        stream_callback=callback)
        stream.start_stream()
        try:
            while not self._stop.is_set():
                time.sleep(0.05)
                # WASAPI loopback delivers NOTHING while nothing is playing. Synthesize silence so
                # speech-to-text notices the pause and the audio clock keeps moving.
                now = time.perf_counter()
                gap = now - max(self._last_real, self._last_synth)
                if gap > 0.15:
                    n = int(TARGET_RATE * gap)
                    with self._emit_lock:
                        self.on_chunk(AudioChunk(b"\x00\x00" * n, now, 0.0))
                    self._last_synth = now
        finally:
            stream.stop_stream()
            stream.close()
            p.terminate()

    def _dispatch(self) -> None:
        while not self._stop.is_set():
            try:
                raw, t = self._q.get(timeout=0.2)
            except queue.Empty:
                continue
            rs = self._rs
            if rs is None:
                continue
            x = rs.process(np.frombuffer(raw, dtype=np.float32))
            if len(x) == 0:
                continue
            rms = float(np.sqrt(np.mean(x * x)))
            with self._emit_lock:
                self.on_chunk(AudioChunk(float_to_pcm16(x), t, rms))
