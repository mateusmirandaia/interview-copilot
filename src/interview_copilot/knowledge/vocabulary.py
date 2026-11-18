"""Vocabulary list (names and technical terms) and transcript replacements.

``vocabulary.txt``: one term per line; lines starting with ``#`` are comments, and `` # text``
after a term is an inline comment (a ``#`` glued to a word, as in ``C#``, is kept).
"""

from __future__ import annotations

import re
from pathlib import Path

_INLINE_COMMENT = re.compile(r"\s+#.*$")


def load_vocabulary(path: str | Path) -> list[str]:
    """Read the vocabulary file; returns unique terms in file order (empty list if missing)."""
    p = Path(path)
    if not p.is_file():
        return []
    terms: list[str] = []
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        term = _INLINE_COMMENT.sub("", line).strip()
        if term and term not in terms:
            terms.append(term)
    return terms


def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    """Case-insensitive whole-phrase pattern; words may be separated by spaces or hyphens."""
    words = phrase.split()
    body = r"[\s\-]*".join(re.escape(w) for w in words) if words else re.escape(phrase)
    start = r"\b" if re.match(r"\w", phrase) else ""
    end = r"\b" if re.search(r"\w$", phrase) else ""
    return re.compile(f"{start}{body}{end}", re.IGNORECASE)


def apply_replacements(text: str, replacements: dict[str, str]) -> str:
    """Apply ``{"wrong phrase": "right phrase"}`` replacements (case-insensitive, whole phrase)."""
    out = text or ""
    for wrong, right in (replacements or {}).items():
        if wrong.strip():
            out = _phrase_pattern(wrong.strip()).sub(lambda _m, r=str(right): r, out)
    return out
