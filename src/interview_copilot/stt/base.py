"""Common speech-to-text interface and the audio clock."""

from __future__ import annotations

import collections
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..audio.capture import TARGET_RATE, AudioChunk

if TYPE_CHECKING:
    from ..settings import Settings


@dataclass
class Utterance:
    """A finished interviewer utterance."""

    text: str
    t_speech_end: float   # estimated perf_counter at the end of the interviewer's speech
    t_detected: float     # perf_counter at which the app decided "the question ended"


class AudioClock:
    """Maps "seconds of audio sent" to wall-clock time (``perf_counter``)."""

    def __init__(self, keep_s: float = 120.0):
        self._cum = 0.0
        self._marks: collections.deque[tuple[float, float]] = collections.deque()
        self._keep = keep_s
        self._lock = threading.Lock()

    def add(self, chunk: AudioChunk) -> None:
        """Register a chunk that was sent to the recognizer."""
        with self._lock:
            self._cum += len(chunk.pcm16) / 2 / TARGET_RATE
            self._marks.append((self._cum, chunk.t_end))
            while self._marks and self._cum - self._marks[0][0] > self._keep:
                self._marks.popleft()

    def wall_time(self, audio_s: float) -> float | None:
        """``perf_counter`` time of audio second ``audio_s`` (None if out of the kept window)."""
        with self._lock:
            for cum, t in self._marks:
                if cum >= audio_s:
                    return t - (cum - audio_s)
        return None

    @property
    def seconds(self) -> float:
        """Total seconds of audio registered."""
        return self._cum


class Transcriber:
    """Base class: feed audio chunks, receive interim text and finished utterances."""

    name = "base"

    def __init__(self, settings: Settings, vocabulary: list[str] | None,
                 on_interim: Callable[[str], None], on_utterance: Callable[[Utterance], None],
                 on_status: Callable[[str], None] = lambda s: None):
        self.settings = settings
        self.vocabulary = list(vocabulary or [])
        self.on_interim = on_interim
        self.on_utterance = on_utterance
        self.on_status = on_status
        self.paused = False

    def start(self) -> None:
        """Start background work (connection, model loading)."""

    def stop(self) -> None:
        """Stop background work."""

    def feed(self, chunk: AudioChunk) -> None:
        """Receive one audio chunk."""

    def set_paused(self, paused: bool) -> None:
        """Pause or resume transcription."""
        self.paused = paused

    def take_pending_text(self) -> str:
        """Text not finalized yet (for the manual suggest hotkey). Clears the buffer."""
        return ""
