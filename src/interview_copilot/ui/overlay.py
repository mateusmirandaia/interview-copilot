"""Floating overlay window (tkinter): always on top, dark background, large font.

The answer area is a scrollable Text widget: the whole answer stays reachable (mouse wheel or the
scroll hotkeys), and a status line says whether the answer is still arriving, finished or was cut.
``tkinter`` is imported when the window is created, so this module imports anywhere.
"""

from __future__ import annotations

import queue
import time
from collections import deque
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from ..ai.parsing import parse_suggestion
from ..render import answer_parts

if TYPE_CHECKING:
    from ..ai.engine import Source
    from ..knowledge.ready_answers import ReadyAnswer
    from ..settings import Settings

BG = "#0f1115"
BG2 = "#181b22"
FG = "#e8e8e8"
DIM = "#8a8f98"
TRANSLATION = "#f5c86b"
INTENT = "#8ab4ff"
GREEN = "#7ee2a8"
READY = "#d9f7e6"
RED = "#ff6b6b"

#: render kind -> Text tag
TAGS = {"label": "label", "ready": "ready", "answer": "ready", "add": "add", "warn": "warn"}


class Overlay:
    """The copilot window. Consumes events from ``events`` (see ``app.py``) on the UI thread."""

    def __init__(self, settings: Settings, events: queue.Queue[tuple], actions: dict[str, Callable[[], None]],
                 ready_answers: dict[str, ReadyAnswer] | None = None):
        import tkinter as tk

        self.tk = tk
        self.settings = settings
        self.events = events
        self.actions = actions
        self.ready_answers = ready_answers or {}
        u = settings.ui
        fam = u.get("font_family", "Segoe UI")
        size = int(u.get("font_size", 14))
        ans_size = int(u.get("answer_font_size", size + 1))
        self.current_qid: int | None = None
        self.lat_hist: deque[float] = deque(maxlen=10)
        self._t_question = 0.0
        self._last_render = ""

        self.root = tk.Tk()
        self.root.title("Interview Copilot")
        self.root.geometry(f"{u.get('width', 600)}x{u.get('height', 820)}+40+40")
        self.root.minsize(380, 420)
        self.root.configure(bg=BG)
        self.root.attributes("-topmost", True)
        try:
            self.root.attributes("-alpha", float(u.get("opacity", 0.94)))
        except tk.TclError:
            pass

        f_small = (fam, max(9, size - 4))
        f_mid = (fam, size)
        self.wrap = int(u.get("width", 600)) - 28

        # ---- top bar: latency + audio level, then status -----------------------------------
        top = tk.Frame(self.root, bg=BG2)
        top.pack(fill="x", side="top")
        self.latency = tk.Label(top, text="latency: -", bg=BG2, fg=DIM, font=f_small, anchor="w")
        self.latency.grid(row=0, column=0, sticky="w", padx=8, pady=(4, 0))
        self.level = tk.Canvas(top, width=60, height=8, bg="#222", highlightthickness=0)
        self.level.grid(row=0, column=1, sticky="e", padx=8)
        self.level_bar = self.level.create_rectangle(0, 0, 0, 8, fill=GREEN, width=0)
        self.status = tk.Label(top, text="Starting...", bg=BG2, fg=DIM, font=f_small, anchor="w",
                               justify="left", wraplength=self.wrap)
        self.status.grid(row=1, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 4))
        top.grid_columnconfigure(0, weight=1)

        # ---- footer: hotkey hints -------------------------------------------------------------
        hk = settings.hotkeys
        hint = (f"{hk.get('suggest', '')} suggest · {hk.get('research', '')} search docs · "
                f"{hk.get('clear', '')} clear · {hk.get('pause', '')} pause · "
                f"{hk.get('scroll_down', '')}/{hk.get('scroll_up', '')} scroll")
        hint = hint.replace("<", "").replace(">", "")
        self.footer = tk.Label(self.root, text=hint, bg=BG2, fg=DIM, font=f_small, anchor="w",
                               justify="left", wraplength=self.wrap)
        self.footer.pack(fill="x", side="bottom")

        # ---- question header ----------------------------------------------------------------
        head = tk.Frame(self.root, bg=BG)
        head.pack(fill="x", side="top", padx=12, pady=(6, 0))
        self.live = tk.Label(head, text="", bg=BG, fg=DIM, font=f_small, anchor="w", justify="left",
                             wraplength=self.wrap)
        self.live.pack(fill="x")
        self.q_original = tk.Label(head, text="", bg=BG, fg=FG, font=f_small, anchor="w", justify="left",
                                   wraplength=self.wrap)
        self.q_original.pack(fill="x", pady=(4, 2))
        self.q_translation = tk.Label(head, text="", bg=BG, fg=TRANSLATION, font=f_mid, anchor="w",
                                      justify="left", wraplength=self.wrap)
        self.q_translation.pack(fill="x")
        self.intent = tk.Label(head, text="", bg=BG, fg=INTENT, font=f_small, anchor="w", justify="left",
                               wraplength=self.wrap)
        self.intent.pack(fill="x", pady=(2, 4))
        self.ans_status = tk.Label(head, text="", bg=BG, fg=DIM, font=f_small, anchor="w")
        self.ans_status.pack(fill="x")

        # ---- answer (scrollable, fills the rest) ----------------------------------------------
        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=(12, 4), pady=(2, 6))
        self.scroll = tk.Scrollbar(body, orient="vertical")
        self.scroll.pack(side="right", fill="y")
        self.answer = tk.Text(body, bg=BG, fg=GREEN, font=(fam, ans_size, "bold"), wrap="word",
                              relief="flat", borderwidth=0, highlightthickness=0,
                              yscrollcommand=self.scroll.set, cursor="arrow",
                              padx=2, pady=2, spacing2=2, spacing3=6)
        self.answer.pack(side="left", fill="both", expand=True)
        self.scroll.config(command=self.answer.yview)
        self.answer.tag_configure("label", foreground=DIM, font=(fam, max(9, size - 3)))
        self.answer.tag_configure("ready", foreground=READY, font=(fam, ans_size))
        self.answer.tag_configure("add", foreground=GREEN, font=(fam, ans_size))
        self.answer.tag_configure("warn", foreground=RED, font=(fam, ans_size, "bold"))
        self.answer.tag_configure("link", foreground=INTENT, font=(fam, max(9, size - 3)))
        self.answer.config(state="disabled")

        # local keys (window focused); global hotkeys are registered by app.start_global_hotkeys
        noop: Callable[[], None] = lambda: None  # noqa: E731
        self.root.bind("<F7>", lambda e: self.actions.get("research", noop)())
        self.root.bind("<F8>", lambda e: self.actions.get("suggest", noop)())
        self.root.bind("<F9>", lambda e: self.actions.get("clear", noop)())
        self.root.bind("<F10>", lambda e: self.actions.get("pause", noop)())
        self.root.bind("<Down>", lambda e: self.scroll_answer(3))
        self.root.bind("<Up>", lambda e: self.scroll_answer(-3))
        self.root.bind("<Configure>", self._on_resize)
        self.root.protocol("WM_DELETE_WINDOW", self._close)

        self.root.after(30, self._poll)
        self.root.after(2000, self._keep_on_top)

    # ---- helpers ------------------------------------------------------------------------------
    def _on_resize(self, event: Any) -> None:
        if event.widget is self.root:
            w = max(200, event.width - 28)
            if abs(w - self.wrap) > 4:
                self.wrap = w
                for lbl in (self.live, self.q_original, self.q_translation, self.intent, self.footer,
                            self.status):
                    lbl.config(wraplength=w)

    def scroll_answer(self, lines: int) -> None:
        """Scroll the answer area by ``lines``."""
        self.answer.yview_scroll(lines, "units")

    def _keep_on_top(self) -> None:
        # full-screen Teams/Zoom windows sometimes steal "topmost"
        self.root.attributes("-topmost", True)
        self.root.after(2000, self._keep_on_top)

    def _close(self) -> None:
        self.actions.get("quit", lambda: None)()
        self.root.destroy()

    def _set_answer(self, parts: list[tuple[str, str]]) -> None:
        key = repr(parts)
        if key == self._last_render:
            return
        self._last_render = key
        first_view = self.answer.yview()[0]
        self.answer.config(state="normal")
        self.answer.delete("1.0", "end")
        for text, tag in parts:
            self.answer.insert("end", text, tag)
        self.answer.config(state="disabled")
        self.answer.yview_moveto(first_view)   # do not jump while the text grows

    def render_suggestion(self, raw: str, complete: bool = False) -> list[tuple[str, str]]:
        """Parse raw model output into tagged parts and update the intent line."""
        s = parse_suggestion(raw, complete=complete)
        if s.no_question:
            self.intent.config(text="(not a question: translation only)")
            return []
        self.intent.config(text=f"Intent: {s.intent}" if s.intent else "")
        return [(t, TAGS[k]) for t, k in answer_parts(s, self.ready_answers, complete)]

    @staticmethod
    def render_sources(sources: list[Source]) -> list[tuple[str, str]]:
        """Tagged parts listing the research sources."""
        if not sources:
            return [("\nSource: no page was cited by the search.\n", "label")]
        parts = [("\nSOURCES (official documentation):\n", "label")]
        parts += [(f"• {src.title}\n{src.url}\n", "link") for src in sources]
        return parts

    def clear(self) -> None:
        """Clear the question and the answer."""
        self.current_qid = None
        for w in (self.live, self.q_original, self.q_translation, self.intent, self.ans_status):
            w.config(text="")
        self._last_render = ""
        self._set_answer([])

    # ---- events (always on the UI thread) -----------------------------------------------------
    def _poll(self) -> None:
        try:
            while True:
                self.handle(*self.events.get_nowait())
        except queue.Empty:
            pass
        self.root.after(30, self._poll)

    def handle(self, kind: str, *args: Any) -> None:
        """Apply one event to the window."""
        if kind == "status":
            self.status.config(text=args[0], fg=DIM)
        elif kind == "level":
            self.level.coords(self.level_bar, 0, 0, min(60, int(args[0] * 600)), 8)
        elif kind == "interim":
            self.live.config(text=args[0][-220:])
        elif kind == "question":
            qid, text = args
            self.current_qid = qid
            self._t_question = time.perf_counter()
            self.q_original.config(text=("..." + text[-300:]) if len(text) > 300 else text)
            self.q_translation.config(text="...")
            self.intent.config(text="")
            self.live.config(text="")
            self.ans_status.config(text="generating answer...", fg=TRANSLATION)
            self._last_render = ""
            self._set_answer([])
            self.answer.yview_moveto(0)
        elif kind == "translation" and args[0] == self.current_qid:
            self.q_translation.config(text=args[1])
        elif kind == "suggestion" and args[0] == self.current_qid:
            self._set_answer(self.render_suggestion(args[1]))
        elif kind == "suggestion_done" and args[0] == self.current_qid:
            self._suggestion_done(*args)
        elif kind == "research_start":
            self.current_qid = args[0]
            self._t_question = time.perf_counter()
            model = self.settings.research.get("model") or self.settings.ai.get("model", "")
            self.ans_status.config(text=f"searching the official documentation ({model})...", fg=INTENT)
            self._last_render = ""
            self._set_answer([("Searching the official documentation...\n", "label")])
            self.answer.yview_moveto(0)
        elif kind == "research_done" and args[0] == self.current_qid:
            self._research_done(*args)
        elif kind == "latency" and args[0] == self.current_qid:
            total, detect, ai = args[1:]
            self.lat_hist.append(total)
            avg = sum(self.lat_hist) / len(self.lat_hist)
            color = GREEN if total <= 2.0 else TRANSLATION if total <= 3.0 else RED
            self.latency.config(text=f"{total:.1f}s (pause {detect:.1f} + AI {ai:.1f}) · avg {avg:.1f}s",
                                fg=color)
        elif kind == "paused":
            self.status.config(fg=RED if args[0] else DIM)
        elif kind == "clear":
            self.clear()
        elif kind == "scroll":
            self.scroll_answer(args[0])
        elif kind == "error":
            self.status.config(text=args[0], fg=RED)
        elif kind == "footer":
            self.footer.config(text=args[0])

    def _suggestion_done(self, qid: int, raw: str, stop: str | None) -> None:
        self._set_answer(self.render_suggestion(raw, complete=True))
        took = time.perf_counter() - self._t_question
        if stop == "max_tokens":
            self.ans_status.config(text="⚠ answer cut off (increase [ai] max_tokens_answer)", fg=RED)
        elif stop == "error":
            self.ans_status.config(text="⚠ error while generating (see the status bar)", fg=RED)
        elif stop != "cancelled":
            self.answer.update_idletasks()
            more = "  ·  scroll for more ↓" if self.answer.yview()[1] < 0.999 else ""
            self.ans_status.config(text=f"✓ complete in {took:.1f}s{more}", fg=GREEN)

    def _research_done(self, qid: int, raw: str, stop: str | None, sources: list[Source]) -> None:
        parts = self.render_suggestion(raw, complete=True)
        parts = [("DOCUMENTATION SEARCH\n", "label")] + parts + self.render_sources(sources)
        self._last_render = ""
        self._set_answer(parts)
        took = time.perf_counter() - self._t_question
        if stop == "error":
            self.ans_status.config(text="⚠ the search failed (see the status bar)", fg=RED)
        elif stop == "max_tokens":
            self.ans_status.config(text="⚠ search cut off (increase [research] max_tokens)", fg=RED)
        elif stop != "cancelled":
            self.ans_status.config(text=f"✓ search done in {took:.1f}s · {len(sources)} source(s)",
                                   fg=GREEN)

    def run(self) -> None:
        """Run the Tk main loop (blocks until the window closes)."""
        self.root.mainloop()
