"""Speech-to-text providers.

``provider = "auto"``:
  1. ``DEEPGRAM_API_KEY`` set -> Deepgram streaming (finalizes ~300 ms after the pause, no GPU needed).
  2. Otherwise -> local faster-whisper (large-v3-turbo on an NVIDIA GPU, small.en on CPU).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from .base import AudioClock, Transcriber, Utterance

if TYPE_CHECKING:
    from ..settings import Settings


def make_transcriber(settings: Settings, vocabulary: list[str], on_interim: Callable[[str], None],
                     on_utterance: Callable[[Utterance], None],
                     on_status: Callable[[str], None]) -> Transcriber:
    """Create the configured transcriber (``[stt] provider``)."""
    provider = str(settings.stt.get("provider") or "auto").lower()
    if provider == "auto":
        provider = "deepgram" if settings.deepgram_key else "whisper"
    if provider == "deepgram":
        from .deepgram import DeepgramTranscriber

        return DeepgramTranscriber(settings, vocabulary, on_interim, on_utterance, on_status)
    if provider == "whisper":
        from .whisper import WhisperTranscriber

        t = WhisperTranscriber(settings, vocabulary, on_interim, on_utterance, on_status)
        if not t.gpu:
            on_status("Warning: no CUDA GPU. Whisper on CPU can take more than 3 s. "
                      "Recommended: Deepgram (set DEEPGRAM_API_KEY).")
        return t
    raise ValueError(f"Unknown [stt] provider: {provider}")


__all__ = ["AudioClock", "Transcriber", "Utterance", "make_transcriber"]
