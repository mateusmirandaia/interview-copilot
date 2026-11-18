"""Turns model output into display parts (used by the overlay window and the terminal)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .ai.parsing import Suggestion
    from .knowledge.ready_answers import ReadyAnswer

#: part kinds: label (small caption), ready (ready answer text), answer (generated), add, warn
KINDS = ("label", "ready", "answer", "add", "warn")


def answer_parts(suggestion: Suggestion, ready_answers: dict[str, ReadyAnswer],
                 complete: bool = False) -> list[tuple[str, str]]:
    """List of ``(text, kind)`` to display for a (possibly partial) suggestion."""
    s = suggestion
    parts: list[tuple[str, str]] = []
    if s.no_question:
        return parts
    if s.model_id:
        ra = ready_answers.get(s.model_id)
        if ra:
            parts.append((f"READY ANSWER · {ra.title}\n", "label"))
            parts.append((ra.text + "\n", "ready"))
            if s.add:
                parts.append((s.add + "\n", "add"))
        else:
            parts.append((f"(ready answer {s.model_id} not found in the profile)\n", "label"))
            if s.answer:
                parts.append((s.answer + "\n", "answer"))
    elif s.answer:
        parts.append(("SUGGESTED ANSWER\n", "label"))
        parts.append((s.answer + "\n", "answer"))
    if s.docs:
        parts.append((f"\n⚠ Official documentation: {s.docs}\n", "warn"))
    return parts
