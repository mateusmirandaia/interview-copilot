"""Parses the model's line-based output format.

::

    READY: <ready-answer ID or NONE>
    ANSWER: <full spoken paragraph, only without a ready answer>
    ADD: <one extra sentence, only with a ready answer>
    DOCS: <conflict with the official documentation>
    INTENT: <what the interviewer wants to assess, in the candidate's native language>

or the single word ``NO_QUESTION``. v1 aliases ``MODEL:`` (= ``READY:``) and ``QUER SABER:``
(= ``INTENT:``) are accepted.
"""

from __future__ import annotations

from dataclasses import dataclass

READY_KEYS = ("READY", "MODEL")
FIELDS: dict[str, str] = {
    "ANSWER": "answer",
    "ADD": "add",
    "DOCS": "docs",
    "INTENT": "intent",
    "QUER SABER": "intent",   # v1 alias
}
BULLETS = ("- ", "* ", "• ")


@dataclass
class Suggestion:
    """Structured view of the model output (partial while streaming)."""

    model_id: str | None = None   # ready-answer ID or None
    model_decided: bool = False   # the READY line arrived complete
    answer: str = ""
    add: str = ""
    docs: str = ""
    intent: str = ""
    no_question: bool = False

    @property
    def has_content(self) -> bool:
        """True when there is something to show (a ready answer or answer text)."""
        return bool(self.model_id or self.answer.strip())


def _key_of(upper_line: str, keys) -> str | None:
    return next((k for k in keys if upper_line.startswith(k + ":")), None)


def parse_suggestion(text: str, complete: bool = False) -> Suggestion:
    """Parse model output, tolerating partial text while streaming.

    The answer paragraph is shown as it arrives; the ``READY:`` line only counts once its line
    has ended (or when ``complete=True``). Lines without a prefix continue the previous field;
    stray bullets are folded into the answer as running text.
    """
    s = Suggestion()
    lines = text.split("\n")
    current: str | None = None
    for i, line in enumerate(lines):
        finished = complete or i < len(lines) - 1
        st = line.strip()
        if not st:
            continue
        up = st.upper()
        if _key_of(up, READY_KEYS):
            current = None
            if finished:
                value = st.split(":", 1)[1].strip()
                s.model_decided = True
                s.model_id = None if value.upper() in ("", "NONE") else value
            continue
        if up.startswith("NO_QUESTION"):
            current = None
            if finished:
                s.no_question = True
            continue
        key = _key_of(up, FIELDS)
        if key:
            current = FIELDS[key]
            setattr(s, current, st.split(":", 1)[1].strip())
        elif current:
            setattr(s, current, (getattr(s, current) + " " + st).strip())
        elif st.startswith(BULLETS):
            s.answer = (s.answer + " " + st[2:].strip()).strip()
    s.no_question = s.no_question and not s.has_content
    return s
