"""Streaming speech-to-text with Deepgram (plain WebSocket, no SDK).

End of question = ``speech_final`` (silence endpointing = ``[stt] pause_ms``) or, as a fallback,
the ``UtteranceEnd`` event.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

from ..audio.capture import TARGET_RATE, AudioChunk
from .base import AudioClock, Transcriber, Utterance

DG_URL = "wss://api.deepgram.com/v1/listen"
MAX_KEYTERMS = 100


class DeepgramParser:
    """Assembles utterances from Deepgram messages (kept apart from the network so it is testable)."""

    def __init__(self, clock: AudioClock, on_interim: Callable[[str], None],
                 on_utterance: Callable[[Utterance], None]):
        self.clock = clock
        self.on_interim = on_interim
        self.on_utterance = on_utterance
        self.finals: list[str] = []
        self.last_word_end: float | None = None
        self.offset = 0.0   # seconds of audio sent before the current connection
        self.lock = threading.Lock()

    def handle(self, msg: dict[str, Any]) -> None:
        """Process one JSON message from Deepgram."""
        typ = msg.get("type")
        if typ == "Results":
            alt = (msg.get("channel", {}).get("alternatives") or [{}])[0]
            text = (alt.get("transcript") or "").strip()
            with self.lock:
                if msg.get("is_final"):
                    if text:
                        self.finals.append(text)
                        words = alt.get("words") or []
                        if words:
                            self.last_word_end = self.offset + float(words[-1].get("end", 0))
                    self.on_interim(" ".join(self.finals))
                    if msg.get("speech_final"):
                        self._emit_locked()
                elif text:
                    self.on_interim(" ".join(self.finals + [text]))
        elif typ == "UtteranceEnd":
            with self.lock:
                if msg.get("last_word_end") is not None and self.last_word_end is None:
                    self.last_word_end = self.offset + float(msg["last_word_end"])
                self._emit_locked()

    def _emit_locked(self) -> None:
        if not self.finals:
            return
        text = " ".join(self.finals).strip()
        now = time.perf_counter()
        t_end = self.clock.wall_time(self.last_word_end) if self.last_word_end is not None else None
        self.finals = []
        self.last_word_end = None
        self.on_utterance(Utterance(text, t_end or now, now))

    def take_pending(self) -> str:
        """Finalized text not emitted yet (clears it)."""
        with self.lock:
            text = " ".join(self.finals).strip()
            self.finals = []
            self.last_word_end = None
            return text


class DeepgramTranscriber(Transcriber):
    """Deepgram live transcription with automatic reconnect."""

    name = "deepgram"

    def __init__(self, settings, vocabulary, on_interim, on_utterance, on_status=lambda s: None):
        super().__init__(settings, vocabulary, on_interim, on_utterance, on_status)
        self.key = settings.deepgram_key
        if not self.key:
            raise RuntimeError("DEEPGRAM_API_KEY is not set.")
        self.clock = AudioClock()
        self._interim_tail = ""
        self.parser = DeepgramParser(self.clock, self._interim, self.on_utterance)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._q: asyncio.Queue[bytes] | None = None
        self._stop = False
        self._last_send = time.perf_counter()

    def _interim(self, text: str) -> None:
        self._interim_tail = text
        self.on_interim(text)

    def url(self) -> str:
        """WebSocket URL with every query parameter (vocabulary included)."""
        s = self.settings.stt
        pause = int(s.get("pause_ms", 700))
        model = str(s.get("deepgram", {}).get("model", "nova-3"))
        params: dict[str, Any] = {
            "model": model,
            "language": s.get("language", "en"),
            "encoding": "linear16",
            "sample_rate": TARGET_RATE,
            "channels": 1,
            "interim_results": "true",
            "smart_format": "true",
            "punctuate": "true",
            "endpointing": pause,
            "utterance_end_ms": max(1000, pause + 300),
            "vad_events": "true",
        }
        query: list[tuple[str, Any]] = list(params.items())
        # nova-3 uses "keyterm" (one per parameter); older models use "keywords"
        for term in self.vocabulary[:MAX_KEYTERMS]:
            if model.startswith("nova-3"):
                query.append(("keyterm", term))
            else:
                query.append(("keywords", f"{term}:2"))
        return f"{DG_URL}?{urlencode(query)}"

    _url = url   # v1 name

    # ---- API ------------------------------------------------------------------------------
    def start(self) -> None:
        threading.Thread(target=self._thread_main, name="deepgram", daemon=True).start()

    def stop(self) -> None:
        self._stop = True

    def feed(self, chunk: AudioChunk) -> None:
        if self.paused or self._loop is None or self._q is None:
            return
        self.clock.add(chunk)
        self._loop.call_soon_threadsafe(self._q.put_nowait, chunk.pcm16)

    def take_pending_text(self) -> str:
        pending = self.parser.take_pending()
        tail = self._interim_tail
        self._interim_tail = ""
        return tail if len(tail) > len(pending) else pending

    # ---- network --------------------------------------------------------------------------
    def _thread_main(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._q = asyncio.Queue()
        self._loop.run_until_complete(self._run_forever())

    async def _run_forever(self) -> None:
        backoff = 1.0
        while not self._stop:
            try:
                await self._session()
                backoff = 1.0
            except Exception as e:  # noqa: BLE001 - reconnect on any network error
                self.on_status(f"Deepgram disconnected: {e}. Reconnecting...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 10)

    async def _session(self) -> None:
        import websockets

        headers = {"Authorization": f"Token {self.key}"}
        try:
            ws_cm = websockets.connect(self.url(), additional_headers=headers, max_size=None)
        except TypeError:   # websockets < 14
            ws_cm = websockets.connect(self.url(), extra_headers=headers, max_size=None)
        async with ws_cm as ws:
            self.on_status("Deepgram connected")
            assert self._q is not None
            while not self._q.empty():   # drop audio buffered during the reconnect
                self._q.get_nowait()
            # Deepgram restarts timestamps at 0 on every connection
            self.parser.offset = self.clock.seconds
            sender = asyncio.create_task(self._sender(ws))
            keep = asyncio.create_task(self._keepalive(ws))
            try:
                async for raw in ws:
                    if isinstance(raw, bytes):
                        continue
                    self.parser.handle(json.loads(raw))
            finally:
                sender.cancel()
                keep.cancel()

    async def _sender(self, ws: Any) -> None:
        assert self._q is not None
        while True:
            data = await self._q.get()
            while not self._q.empty() and len(data) < TARGET_RATE * 2 * 0.25:   # batch small chunks
                data += self._q.get_nowait()
            await ws.send(data)
            self._last_send = time.perf_counter()

    async def _keepalive(self, ws: Any) -> None:
        while True:
            await asyncio.sleep(3)
            if time.perf_counter() - self._last_send > 3:
                await ws.send(json.dumps({"type": "KeepAlive"}))
