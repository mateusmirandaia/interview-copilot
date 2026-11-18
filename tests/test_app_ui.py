"""CopilotApp without audio (event queue) and the overlay (skipped without tkinter)."""

from __future__ import annotations

import queue
import time
from pathlib import Path

import pytest

from interview_copilot.knowledge.loader import Knowledge


def _drain(events: queue.Queue, until: str, timeout: float = 10) -> list[tuple]:
    seen: list[tuple] = []
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            ev = events.get(timeout=0.1)
        except queue.Empty:
            continue
        seen.append(ev)
        if ev[0] == until:
            return seen
    raise AssertionError(f"no {until!r} event; got {[e[0] for e in seen]}")


def test_app_ask_posts_events(mock_api, profile: Path, make_settings):
    from interview_copilot.app import CopilotApp

    events: queue.Queue[tuple] = queue.Queue()
    app = CopilotApp(make_settings(profile), Knowledge.load(profile), events, with_audio=False)
    assert app.stt is None and app.capture is None
    assert set(app.actions()) == {"suggest", "research", "clear", "pause", "scroll_down", "scroll_up", "quit"}
    now = time.perf_counter()
    qid = app.ask("How do you test an API?", now, now)
    seen = _drain(events, "suggestion_done")
    kinds = [e[0] for e in seen]
    assert ("question", qid, "How do you test an API?") in seen
    assert "translation" in kinds and "suggestion" in kinds and "latency" in kinds
    done = next(e for e in seen if e[0] == "suggestion_done")
    assert done[1] == qid and "ANSWER:" in done[2] and done[3] == "end_turn"

    app.action_scroll_up()
    app.action_pause()
    seen = _drain(events, "status")
    assert ("scroll", -4) in seen and ("paused", True) in seen and seen[-1] == ("status", "PAUSED")
    app.action_clear()
    assert _drain(events, "clear")[-1] == ("clear",)


def test_app_research_without_question(mock_api, profile: Path, make_settings):
    from interview_copilot.app import CopilotApp

    events: queue.Queue[tuple] = queue.Queue()
    app = CopilotApp(make_settings(profile), Knowledge.load(profile), events, with_audio=False)
    app.action_research()
    assert _drain(events, "status")[-1] == ("status", "No question to research yet.")
    assert mock_api.requests == []


def test_overlay_imports_without_tkinter_and_renders_sources():
    from interview_copilot.ai.engine import Source
    from interview_copilot.render import KINDS
    from interview_copilot.ui.overlay import TAGS, Overlay

    assert set(KINDS) <= set(TAGS)
    assert Overlay.render_sources([]) == [("\nSource: no page was cited by the search.\n", "label")]
    parts = Overlay.render_sources([Source("Asyncio", "https://docs.python.org/3/a")])
    assert parts[1] == ("• Asyncio\nhttps://docs.python.org/3/a\n", "link")


def test_overlay_window(mock_api, profile: Path, make_settings):
    """Needs tkinter and a display; skipped otherwise (e.g. on CI)."""
    tk = pytest.importorskip("tkinter")
    try:
        tk.Tk().destroy()
    except tk.TclError:
        pytest.skip("no display")
    from interview_copilot.ui.overlay import Overlay

    events: queue.Queue[tuple] = queue.Queue()
    k = Knowledge.load(profile)
    ov = Overlay(make_settings(profile), events, {}, ready_answers=k.ready_answers)
    try:
        parts = ov.render_suggestion("READY: 1\nINTENT: pitch", complete=True)
        assert parts[0][1] == "label" and "Tell me about yourself" in parts[0][0]
        assert ov.render_suggestion("NO_QUESTION", complete=True) == []
    finally:
        ov.root.destroy()
