"""Local speech-to-text with faster-whisper + energy-based pause detection (VAD).

With an NVIDIA GPU (CUDA) it uses large-v3-turbo and shows live partial transcripts. Without a
GPU it uses small.en on CPU: it works, but latency is usually above 2-3 s.
``faster_whisper`` is imported lazily.
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Any

import numpy as np

from ..audio.capture import TARGET_RATE, AudioChunk
from .base import Transcriber, Utterance

#: phrases Whisper tends to "hallucinate" on near-silent audio
HALLUCINATIONS = {"thank you.", "thanks for watching!", "thank you for watching.", "you", "bye.", "so", "."}


def cuda_available() -> bool:
    """True when ctranslate2 sees at least one CUDA device."""
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:  # noqa: BLE001 - missing library or driver = no GPU
        return False


class EnergyVAD:
    """Simple state machine: speech starts after 2 chunks above the threshold and ends after
    ``pause_ms`` below it (or at ``max_segment_s``)."""

    def __init__(self, threshold: float, pause_ms: int, preroll_ms: int = 300, max_segment_s: float = 25.0):
        self.threshold = threshold
        self.pause_s = pause_ms / 1000
        self.preroll = int(TARGET_RATE * preroll_ms / 1000)
        self.max_samples = int(TARGET_RATE * max_segment_s)
        self.reset()

    def reset(self) -> None:
        """Forget any speech in progress."""
        self.in_speech = False
        self.loud_run = 0
        self.silence_s = 0.0
        self.buf: list[np.ndarray] = []
        self.pre = np.zeros(0, dtype=np.float32)
        self.t_last_voice = 0.0

    def push(self, x: np.ndarray, rms: float, t_end: float) -> tuple[str, np.ndarray, float] | None:
        """Return ``('end', audio, t_last_voice)`` when an utterance ends, otherwise None."""
        dur = len(x) / TARGET_RATE
        loud = rms >= self.threshold
        if not self.in_speech:
            self.pre = np.concatenate([self.pre, x])[-self.preroll:]
            self.loud_run = self.loud_run + 1 if loud else 0
            if self.loud_run >= 2:
                self.in_speech = True
                self.buf = [self.pre.copy()]
                self.silence_s = 0.0
                self.t_last_voice = t_end
            return None
        self.buf.append(x)
        if loud:
            self.silence_s = 0.0
            self.t_last_voice = t_end
        else:
            self.silence_s += dur
        total = sum(len(b) for b in self.buf)
        if self.silence_s >= self.pause_s or total >= self.max_samples:
            audio = np.concatenate(self.buf)
            t_voice = self.t_last_voice
            self.in_speech = False
            self.loud_run = 0
            self.buf = []
            self.pre = np.zeros(0, dtype=np.float32)
            return ("end", audio, t_voice)
        return None

    def current_audio(self) -> np.ndarray | None:
        """Audio of the utterance in progress (None when not in speech)."""
        return np.concatenate(self.buf) if self.in_speech and self.buf else None


class WhisperTranscriber(Transcriber):
    """faster-whisper transcription in a background thread."""

    name = "whisper"

    def __init__(self, settings, vocabulary, on_interim, on_utterance, on_status=lambda s: None):
        super().__init__(settings, vocabulary, on_interim, on_utterance, on_status)
        w = settings.stt.get("whisper", {})
        self.gpu = cuda_available()
        self.model_name = w.get("model_gpu", "large-v3-turbo") if self.gpu else w.get("model_cpu", "small.en")
        self.compute_type = (w.get("compute_type_gpu", "float16") if self.gpu
                             else w.get("compute_type_cpu", "int8"))
        self.interim_every = float(w.get("interim_every_s", 1.0)) if self.gpu else 0.0
        self.language = settings.stt.get("language", "en")
        # the initial prompt steers the spelling of names and technical terms
        self.initial_prompt = ("Job interview. Glossary: " + ", ".join(self.vocabulary) + ".") \
            if self.vocabulary else None
        self.vad = EnergyVAD(float(w.get("vad_threshold", 0.01)), int(settings.stt.get("pause_ms", 700)))
        self._q: queue.Queue[AudioChunk] = queue.Queue()
        self._stop = threading.Event()
        self._model: Any = None
        self._last_interim = 0.0
        self._interim_text = ""
        self.name = f"whisper-{'gpu' if self.gpu else 'cpu'} ({self.model_name})"

    def start(self) -> None:
        threading.Thread(target=self._run_safe, name="whisper", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def feed(self, chunk: AudioChunk) -> None:
        if not self.paused:
            self._q.put(chunk)

    def take_pending_text(self) -> str:
        audio = self.vad.current_audio()
        self.vad.reset()
        if audio is not None and self._model is not None:
            return self._transcribe(audio)
        return self._interim_text

    def _transcribe(self, audio: np.ndarray, fast: bool = False) -> str:
        segments, _ = self._model.transcribe(
            audio, language=self.language, beam_size=1 if fast else 2, vad_filter=False,
            condition_on_previous_text=False, without_timestamps=True, initial_prompt=self.initial_prompt)
        text = " ".join(s.text.strip() for s in segments).strip()
        return "" if text.lower() in HALLUCINATIONS else text

    def _run_safe(self) -> None:
        try:
            self._run()
        except ImportError:
            self.on_status("faster-whisper is not installed: pip install \"interview-copilot[whisper]\" "
                           "or set DEEPGRAM_API_KEY.")
        except Exception as e:  # noqa: BLE001 - shown in the status bar
            self.on_status(f"Whisper error: {e}")

    def _run(self) -> None:
        from faster_whisper import WhisperModel

        self.on_status(f"Loading {self.model_name} ({'GPU' if self.gpu else 'CPU'})...")
        self._model = WhisperModel(self.model_name, device="cuda" if self.gpu else "cpu",
                                   compute_type=self.compute_type)
        self._transcribe(np.zeros(TARGET_RATE, dtype=np.float32), fast=True)   # warm-up
        self.on_status(f"Whisper ready ({self.name})")
        while not self._stop.is_set():
            try:
                ch = self._q.get(timeout=0.2)
            except queue.Empty:
                continue
            x = np.frombuffer(ch.pcm16, dtype="<i2").astype(np.float32) / 32768
            ev = self.vad.push(x, ch.rms, ch.t_end)
            if ev:
                _, audio, t_voice = ev
                text = self._transcribe(audio)
                self._interim_text = ""
                if text:
                    self.on_interim(text)
                    self.on_utterance(Utterance(text, t_voice, time.perf_counter()))
                continue
            # live partial (GPU only), without delaying the queue
            if self.interim_every and self.vad.in_speech and self._q.qsize() < 3:
                now = time.perf_counter()
                if now - self._last_interim >= self.interim_every:
                    self._last_interim = now
                    audio = self.vad.current_audio()
                    if audio is not None:
                        self._interim_text = self._transcribe(audio, fast=True)
                        self.on_interim(self._interim_text)
