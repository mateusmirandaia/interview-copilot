"""Orchestrates capture -> speech-to-text -> AI -> UI through an event queue.

Events posted to ``events`` (consumed by the overlay on the UI thread)::

    ("status", text)                      ("error", text)          ("footer", text)
    ("level", rms)                        ("interim", text)        ("question", qid, text)
    ("translation", qid, text)            ("suggestion", qid, raw)
    ("suggestion_done", qid, raw, stop)   ("latency", qid, total, detect, ai)
    ("research_start", qid)               ("research_done", qid, raw, stop, sources)
    ("paused", bool)                      ("clear",)               ("scroll", lines)
"""

from __future__ import annotations

import itertools
import queue
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from .ai.engine import CopilotEngine

if TYPE_CHECKING:
    from .audio.capture import AudioChunk
    from .knowledge.loader import Knowledge
    from .settings import Settings
    from .stt.base import Utterance


class CopilotApp:
    """The running copilot: audio (optional), transcription, engine and UI events."""

    def __init__(self, settings: Settings, knowledge: Knowledge, events: queue.Queue[tuple],
                 with_audio: bool = True):
        self.settings = settings
        self.knowledge = knowledge
        self.events = events
        self.with_audio = with_audio
        self.paused = False
        self._ids = itertools.count(1)
        self._last_question = ""
        self._last_level = 0.0
        a = settings.ai
        self.auto_suggest = bool(a.get("auto_suggest", True))
        self.min_words = int(a.get("min_words_auto", 4))

        self.ctx_info = knowledge.summary()
        tokens = knowledge.approx_tokens()
        warn = int(settings.knowledge.get("warn_tokens", 100_000))
        self.ctx_warning = ""
        if tokens > warn:
            self.ctx_warning = (f"⚠ Large context: ~{tokens:,} tokens (warning above {warn:,}). "
                                "Answers may be slower and more expensive.")
        if not knowledge.documents:
            self.status(f"Warning: no .md/.txt/.docx files in {knowledge.profile.path}")
        if not knowledge.ready_answers:
            self.status("Warning: no ready answers loaded (check [ready_answers] in profile.toml)")

        self.engine = CopilotEngine(settings, knowledge, on_status=self.status)
        self.stt = None
        self.capture = None
        if with_audio:
            from .audio.capture import LoopbackCapture
            from .stt import make_transcriber

            self.stt = make_transcriber(settings, knowledge.vocabulary, self._on_interim,
                                        self._on_utterance, self.status)
            self.capture = LoopbackCapture(self._on_chunk, str(settings.audio.get("device_name", "")),
                                           int(settings.audio.get("chunk_ms", 50)))

    @property
    def ready_answers(self) -> dict:
        """Ready answers by ID (for the overlay)."""
        return self.knowledge.ready_answers

    # ---- helpers ----------------------------------------------------------------------------
    def post(self, *event: Any) -> None:
        """Put an event on the UI queue."""
        self.events.put(event)

    def status(self, text: str) -> None:
        """Show a status message."""
        self.post("status", text)

    def actions(self) -> dict[str, Callable[[], None]]:
        """Action callbacks for the overlay (local keys) and global hotkeys."""
        return {
            "suggest": self.action_suggest,
            "research": self.action_research,
            "clear": self.action_clear,
            "pause": self.action_pause,
            "scroll_down": self.action_scroll_down,
            "scroll_up": self.action_scroll_up,
            "quit": self.stop,
        }

    # ---- lifecycle --------------------------------------------------------------------------
    def start(self) -> None:
        """Warm the cache and start audio + transcription."""
        self.status(f"Context: {self.ctx_info} · warming up the AI...")
        if self.ctx_warning:
            self.post("error", self.ctx_warning)
        threading.Thread(target=self.engine.warm_cache, daemon=True, name="warm-cache").start()
        if self.stt and self.capture:
            self.stt.start()
            self.capture.start()
        threading.Thread(target=self._announce, daemon=True, name="announce").start()

    def _announce(self) -> None:
        time.sleep(4)
        if self.stt and self.capture:
            self.post("footer",
                      f"Audio: {self.capture.device_label} · STT: {self.stt.name} · {self.ctx_info}")
        else:
            self.post("footer", f"SIMULATION (no audio) · {self.ctx_info}")

    def stop(self) -> None:
        """Stop audio and transcription."""
        if self.capture:
            self.capture.stop()
        if self.stt:
            self.stt.stop()

    def simulate(self, question: str, delay: float = 3.0) -> None:
        """Inject a question as if the interviewer had just finished speaking."""
        def run() -> None:
            time.sleep(delay)   # let the cache warm up
            now = time.perf_counter()
            self.post("interim", question)
            self.ask(question, now, now, suggest=True)

        threading.Thread(target=run, daemon=True, name="simulate").start()

    # ---- capture / transcription callbacks ---------------------------------------------------
    def _on_chunk(self, chunk: AudioChunk) -> None:
        now = time.perf_counter()
        if now - self._last_level > 0.1:
            self._last_level = now
            self.post("level", 0.0 if self.paused else chunk.rms)
        if self.stt:
            self.stt.feed(chunk)

    def _on_interim(self, text: str) -> None:
        if not self.paused:
            self.post("interim", text)

    def _on_utterance(self, u: Utterance) -> None:
        if self.paused or not u.text.strip():
            return
        if len(u.text.split()) < self.min_words:
            self.post("interim", u.text)   # "Okay.", "Great." -> only shown
            return
        self.ask(u.text, u.t_speech_end, u.t_detected, suggest=self.auto_suggest)

    # ---- AI ---------------------------------------------------------------------------------
    def ask(self, text: str, t_speech_end: float, t_detected: float, suggest: bool = True) -> int:
        """Send a question to the engine; returns its question ID."""
        qid = next(self._ids)
        self._last_question = text
        self.post("question", qid, text)
        last_raw = [""]

        def first_content(t: float) -> None:
            self.post("latency", qid, t - t_speech_end, t_detected - t_speech_end, t - t_detected)

        def on_suggestion(raw: str) -> None:
            last_raw[0] = raw
            self.post("suggestion", qid, raw)

        def done() -> None:
            s = self.engine.stats
            if s.calls:
                stt = self.stt.name if self.stt else "simulation"
                self.post("footer", f"STT: {stt} · {self.ctx_info} · cache read {s.cache_read} tok "
                                    f"in {s.calls} calls")

        self.engine.answer(
            text,
            on_translation=lambda t: self.post("translation", qid, t),
            on_suggestion=on_suggestion,
            on_first_content=first_content,
            on_suggestion_done=lambda stop: self.post("suggestion_done", qid, last_raw[0], stop),
            on_done=done,
            on_error=lambda m: self.post("error", m),
            suggest=suggest,
        )
        return qid

    # ---- hotkey actions ---------------------------------------------------------------------
    def action_suggest(self) -> None:
        """Answer the pending transcript now (or repeat the last question)."""
        text = (self.stt.take_pending_text().strip() if self.stt else "") or self._last_question
        if not text:
            self.status("Nothing transcribed yet.")
            return
        now = time.perf_counter()
        self.ask(text, now, now, suggest=True)

    def action_research(self) -> None:
        """Redo the last answer with a web search on the profile's documentation domains."""
        question = self._last_question
        if not question:
            self.status("No question to research yet.")
            return
        qid = next(self._ids)
        self.post("research_start", qid)
        last_raw = [""]

        def on_text(t: str) -> None:
            last_raw[0] = t
            self.post("suggestion", qid, t)

        self.engine.research(
            question,
            on_text=on_text,
            on_done=lambda raw, stop, sources: self.post("research_done", qid, raw or last_raw[0],
                                                         stop, sources),
            on_error=lambda m: self.post("error", m))

    def action_clear(self) -> None:
        """Cancel the current answer and clear the window."""
        self.engine.cancel()
        if self.stt:
            self.stt.take_pending_text()
        self.post("clear")

    def action_scroll_down(self) -> None:
        """Scroll the answer down."""
        self.post("scroll", 4)

    def action_scroll_up(self) -> None:
        """Scroll the answer up."""
        self.post("scroll", -4)

    def action_pause(self) -> None:
        """Toggle pause (stops transcription and cancels the current answer)."""
        self.paused = not self.paused
        if self.stt:
            self.stt.set_paused(self.paused)
        if self.paused:
            self.engine.cancel()
        self.post("paused", self.paused)
        name = self.stt.name if self.stt else "simulation"
        self.status("PAUSED" if self.paused else f"LIVE · {name}")


def start_global_hotkeys(settings: Settings, events: queue.Queue[tuple], app: CopilotApp) -> Any:
    """Register global hotkeys with pynput (they work while the call window has focus).

    Returns the listener, or None when pynput is missing or a hotkey is invalid.
    """
    try:
        from pynput import keyboard
    except Exception:  # noqa: BLE001 - ImportError, or no display backend on Linux
        events.put(("status", "pynput unavailable: only F7-F10 work, with the window focused"))
        return None
    hk = settings.hotkeys
    defaults = {"suggest": "<ctrl>+<alt>+s", "research": "<ctrl>+<alt>+d", "clear": "<ctrl>+<alt>+c",
                "pause": "<ctrl>+<alt>+p", "scroll_down": "<ctrl>+<alt>+<down>",
                "scroll_up": "<ctrl>+<alt>+<up>"}
    actions = app.actions()
    mapping = {str(hk.get(name, combo)): actions[name]
               for name, combo in defaults.items() if hk.get(name, combo)}
    try:
        listener = keyboard.GlobalHotKeys(mapping)
    except ValueError as e:
        events.put(("status", f"Invalid hotkey in settings: {e}"))
        return None
    listener.daemon = True
    listener.start()
    return listener
