"""Ready (prepared) answers, shown verbatim when the interviewer's question matches.

The model only picks WHICH answer fits (returns its ID); the text on screen comes from the file,
word for word.

- Markdown: every ``## `` or ``### `` heading is one answer; IDs ``1``, ``2``, ``3``... in order.
- Word (.docx): numbered ``Heading 2`` ("3c. A challenging integration") gives ID ``3c``;
  ``Heading 3`` inside it gives ``3c.1``, ``3c.2``... (v1 scheme).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

QUOTE_CHARS = ("“", '"')
_COACHING = re.compile(r"(?i)^(tip|note|rules|context)\s*:|^if asked\b")
_LABEL_BEFORE_QUOTE = re.compile(r"^[^“\"]{1,60}?:\s*(?=[“\"])")


@dataclass
class ReadyAnswer:
    """One prepared answer."""

    id: str
    title: str
    text: str

    @property
    def label(self) -> str:
        return self.title


def clean_paragraph(paragraph: str) -> str:
    """Keep only the spoken text.

    Drops coaching lines (``Tip:``, ``Note:``, ``Rules:``, ``Context:``, ``If asked...``) and strips a
    short label before a quoted line (``With the manager: "..."`` -> ``"..."``).
    """
    t = paragraph.strip()
    if _COACHING.match(t):
        return ""
    return _LABEL_BEFORE_QUOTE.sub("", t)


def _excluded(title: str, number: str | None, exclude: set[str]) -> bool:
    return title.strip().lower() in exclude or (number is not None and number.lower() in exclude)


def parse_markdown(path: str | Path, exclude: list[str] | None = None) -> list[ReadyAnswer]:
    """Parse a markdown ready-answers file (``##``/``###`` headings; ``#`` titles are ignored)."""
    exclude_set = {str(e).strip().lower() for e in (exclude or [])}
    text = Path(path).read_text(encoding="utf-8-sig")
    answers: list[ReadyAnswer] = []
    current: dict | None = None
    in_fence = False

    def close() -> None:
        if current is None:
            return
        lines = [clean_paragraph(p) for p in current["lines"]]
        body = [ln for ln in lines if ln]
        if body:
            answers.append(ReadyAnswer(str(len(answers) + 1), current["title"], "\n".join(body)))

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        m = None if in_fence else re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", stripped)
        if m:
            close()
            current = None
            level, title = len(m.group(1)), m.group(2).strip()
            if level in (2, 3) and not _excluded(title, None, exclude_set):
                current = {"title": title, "lines": []}
            continue
        if current is not None and stripped:
            current["lines"].append(stripped)
    close()
    return answers


def _heading_level(style: str | None) -> int:
    if not style:
        return 0
    m = re.match(r"(?i)^heading\s*(\d)$", style.strip())
    return int(m.group(1)) if m else 0


def _section_number(title: str) -> str | None:
    m = re.match(r"^(\d+[a-z]?)\.\s", title.strip())
    return m.group(1) if m else None


def parse_docx(path: str | Path, exclude: list[str] | None = None) -> list[ReadyAnswer]:
    """Parse a Word ready-answers file (v1 scheme).

    - Numbered Heading 2 ("3c. A challenging integration") -> ID ``3c``.
    - Heading 3 inside a numbered section -> ``3c.1``, ``3c.2``...
    - Answer text = paragraphs with quoted speech; if the section has no quotes, every paragraph.
      Coaching lines are dropped (see :func:`clean_paragraph`).
    - ``exclude``: heading texts (exact) or section numbers that are not answers.
    """
    import docx  # python-docx

    exclude_set = {str(e).strip().lower() for e in (exclude or [])}
    document = docx.Document(str(path))
    answers: list[ReadyAnswer] = []
    current: dict | None = None
    parent_num: str | None = None
    parent_skipped = False
    sub_count = 0

    def close() -> None:
        if not current:
            return
        paras = [clean_paragraph(p) for p in current["paras"] if p.strip()]
        paras = [p for p in paras if p]
        quoted = [p for p in paras if any(q in p for q in QUOTE_CHARS)]
        body = quoted or paras
        if body:
            answers.append(ReadyAnswer(current["id"], current["title"], "\n".join(body)))

    for para in document.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        level = _heading_level(para.style.name if para.style is not None else None)
        if level == 2:
            close()
            current = None
            parent_num = _section_number(text)
            parent_skipped = _excluded(text, parent_num, exclude_set)
            sub_count = 0
            if parent_num and not parent_skipped:
                current = {"id": parent_num, "title": text, "paras": []}
        elif level == 3:
            close()
            current = None
            if parent_num and not parent_skipped and not _excluded(text, None, exclude_set):
                sub_count += 1
                current = {"id": f"{parent_num}.{sub_count}", "title": f"{parent_num}. {text}", "paras": []}
        elif level == 1:
            close()
            current = None
            parent_num = None
        elif current is not None:
            current["paras"].append(text)
    close()
    return answers


def load_ready_answers(path: str | Path | None, exclude: list[str] | None = None) -> list[ReadyAnswer]:
    """Load ready answers from a ``.md`` or ``.docx`` file (empty list if missing or unsupported)."""
    if not path:
        return []
    p = Path(path)
    if not p.is_file():
        return []
    suffix = p.suffix.lower()
    if suffix == ".docx":
        return parse_docx(p, exclude)
    if suffix in (".md", ".txt"):
        return parse_markdown(p, exclude)
    return []


def build_catalog(answers: list[ReadyAnswer]) -> str:
    """Catalog sent to the model: ``<ready_answer_catalog>`` with one ``ID | Title`` line per answer."""
    lines = ["<ready_answer_catalog>"]
    lines += [f"{a.id} | {a.title}" for a in answers]
    lines.append("</ready_answer_catalog>")
    return "\n".join(lines)
