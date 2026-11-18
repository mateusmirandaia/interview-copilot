"""Terminal output: used by ``simulate``, ``check`` and ``mvp`` (no window needed)."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from .ai.engine import CopilotEngine
from .ai.parsing import parse_suggestion
from .render import answer_parts

if TYPE_CHECKING:
    from .knowledge.loader import Knowledge
    from .settings import Settings

Out = Callable[[str], None]


def build_engine(settings: Settings, knowledge: Knowledge, out: Out = print) -> CopilotEngine:
    """Create the engine exactly like the app does, and print a one-line context summary."""
    out(f"Profile: {knowledge.profile.name} ({knowledge.profile.target_role}) · {knowledge.summary()}")
    return CopilotEngine(settings, knowledge, on_status=lambda s: out(f"[AI] {s}"))


def count_tokens(settings: Settings, knowledge: Knowledge) -> tuple[int, bool]:
    """Tokens of the cached system block: exact via the API when a key is set, else estimated.

    Returns ``(tokens, exact)``.
    """
    text = knowledge.context_block() + "\n" + knowledge.catalog()
    if settings.anthropic_key:
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=settings.anthropic_key, max_retries=1, timeout=30)
            r = client.messages.count_tokens(model=str(settings.ai.get("model", "claude-haiku-5-5")),
                                             messages=[{"role": "user", "content": text}])
            return int(r.input_tokens), True
        except Exception:  # noqa: BLE001 - fall back to the estimate
            pass
    return knowledge.approx_tokens(), False


def ask_and_print(engine: CopilotEngine, question: str, out: Out = print, *, t_ref: float | None = None,
                  suggest: bool = True, timeout: float = 25.0) -> dict[str, Any]:
    """Ask a question, wait for it to finish and print it the way the window would show it.

    Returns a dict with ``translation``, ``raw``, ``stop``, ``suggestion`` (parsed) and the
    ``perf_counter`` marks ``tr`` (translation started), ``first`` (first content) and ``end``.
    """
    t0 = t_ref if t_ref is not None else time.perf_counter()
    res: dict[str, Any] = {"translation": "", "raw": "", "stop": None}
    marks: dict[str, float] = {}
    done = threading.Event()

    def on_translation(text: str) -> None:
        marks.setdefault("tr", time.perf_counter())
        res["translation"] = text

    engine.answer(question,
                  on_translation=on_translation,
                  on_suggestion=lambda t: res.__setitem__("raw", t),
                  on_first_content=lambda t: marks.setdefault("first", t),
                  on_suggestion_done=lambda stop: res.__setitem__("stop", stop),
                  on_done=done.set, on_error=lambda m: out(f"[error] {m}"), suggest=suggest)
    if not done.wait(timeout):
        out(f"[error] timed out after {timeout:.0f}s")
    marks["end"] = time.perf_counter()

    out(f"TRANSLATION: {res['translation'].strip()}")
    if suggest:
        s = parse_suggestion(res["raw"], complete=True)
        res["suggestion"] = s
        if s.no_question:
            out("(not a question: translation only)")
        else:
            if s.intent:
                out(f"INTENT: {s.intent}")
            for text, kind in answer_parts(s, engine.knowledge.ready_answers, complete=True):
                prefix = "" if kind == "label" else "  "
                for line in text.rstrip("\n").splitlines():
                    out(prefix + line)
        if res["stop"] == "max_tokens":
            out("  ! answer cut off by max_tokens")
    timing = []
    if "tr" in marks:
        timing.append(f"translation started {marks['tr'] - t0:.2f}s")
    if "first" in marks:
        timing.append(f"first content {marks['first'] - t0:.2f}s")
    timing.append(f"complete {marks['end'] - t0:.2f}s")
    out("   time: " + " · ".join(timing) + "\n")
    res.update(marks)
    return res


def research_and_print(engine: CopilotEngine, question: str, out: Out = print,
                       timeout: float = 90.0) -> dict[str, Any]:
    """Run the documentation research and print the answer with its sources."""
    t0 = time.perf_counter()
    res: dict[str, Any] = {"raw": "", "stop": None, "sources": []}
    done = threading.Event()

    def on_done(raw: str, stop: str | None, sources: list) -> None:
        res.update(raw=raw, stop=stop, sources=sources)
        done.set()

    engine.research(question, on_text=lambda t: None, on_done=on_done, on_error=lambda m: out(f"[error] {m}"))
    if not done.wait(timeout):
        out(f"[error] research timed out after {timeout:.0f}s")
    s = parse_suggestion(res.get("raw", ""), complete=True)
    out("DOCUMENTATION SEARCH")
    if s.intent:
        out(f"INTENT: {s.intent}")
    for text, kind in answer_parts(s, {}, complete=True):
        for line in text.rstrip("\n").splitlines():
            out(("" if kind == "label" else "  ") + line)
    out("SOURCES:")
    for src in res.get("sources", []):
        out(f"  - {src.title}\n    {src.url}")
    if not res.get("sources"):
        out("  (none)")
    out(f"   time: {time.perf_counter() - t0:.1f}s · stop: {res.get('stop')}\n")
    return res
