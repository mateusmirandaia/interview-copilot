"""Loads a profile folder ("knowledge pack") into one static, cacheable context block.

Layout (see ``profiles/README.md``)::

    profiles/<name>/
      profile.toml  vocabulary.txt
      01-instructions/  02-resume/  03-projects/  04-skills/
      05-ready-answers/  06-job/  07-official-docs/

``.md``, ``.txt`` and ``.docx`` files inside the numbered folders are read recursively, sorted by path.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .ready_answers import ReadyAnswer, build_catalog, load_ready_answers
from .vocabulary import load_vocabulary

EXTENSIONS = {".md", ".txt", ".docx"}
SKIP_FILES = {"links.txt"}

#: folder number -> document kind
KINDS: dict[str, str] = {
    "01": "instructions",
    "02": "resume",
    "03": "projects",
    "04": "skills",
    "05": "ready_answers",
    "06": "job",
    "07": "official_docs",
}

#: kind -> section tag in the context block, in output order
SECTIONS: list[tuple[str, str]] = [
    ("instructions", "instructions"),
    ("resume", "resume"),
    ("projects", "projects"),
    ("skills", "skills"),
    ("job", "job"),
    ("ready_answers", "ready_answers_source"),
    ("official_docs", "official_docs"),
]

DEFAULT_READY_ANSWERS = "05-ready-answers/ready-answers.md"


def approx_tokens(text: str) -> int:
    """Rough token estimate (about 3.2 characters per token)."""
    return int(len(text) / 3.2)


@dataclass
class Document:
    """One context file. ``path`` is relative to the profile folder."""

    path: Path
    text: str
    kind: str


@dataclass
class Profile:
    """Candidate metadata from ``profile.toml``. ``meta`` is the whole parsed file."""

    path: Path
    name: str
    target_role: str
    native_language: str
    meta: dict[str, Any] = field(default_factory=dict)


def read_docx_text(path: Path) -> str:
    """Plain text of a Word file: paragraphs, then table rows as ``a | b | c``."""
    import docx  # python-docx

    d = docx.Document(str(path))
    parts = [p.text for p in d.paragraphs if p.text.strip()]
    for table in d.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def read_text_file(path: Path) -> str:
    """Read a text file trying UTF-8, then Windows-1252, then Latin-1."""
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def kind_for_folder(folder_name: str) -> str | None:
    """Document kind for a numbered folder name such as ``03-projects`` (None if not numbered)."""
    m = re.match(r"^(\d{2})[-_ ]", folder_name)
    return KINDS.get(m.group(1)) if m else None


def _skipped(rel: Path) -> bool:
    if any(part.lower() == "evals" for part in rel.parts):
        return True
    if any(part.startswith(("~$", "_", ".")) for part in rel.parts):
        return True
    return rel.name.lower() in SKIP_FILES


def load_documents(profile_path: Path) -> list[Document]:
    """Read every context document of the numbered folders, sorted by relative path."""
    docs: list[Document] = []
    if not profile_path.is_dir():
        return docs
    for folder in sorted(p for p in profile_path.iterdir() if p.is_dir()):
        kind = kind_for_folder(folder.name)
        if kind is None:
            continue
        for p in sorted(folder.rglob("*")):
            rel = p.relative_to(profile_path)
            if not p.is_file() or p.suffix.lower() not in EXTENSIONS or _skipped(rel):
                continue
            try:
                text = read_docx_text(p) if p.suffix.lower() == ".docx" else read_text_file(p)
            except Exception as e:  # noqa: BLE001 - a broken file must not stop the app
                text = f"[could not read file: {e}]"
            if text.strip():
                docs.append(Document(rel, text.strip(), kind))
    return docs


def _load_profile_toml(profile_path: Path) -> dict[str, Any]:
    p = profile_path / "profile.toml"
    if not p.is_file():
        return {}
    with open(p, "rb") as f:
        return tomllib.load(f)


def _find_ready_answers_file(profile_path: Path, meta: dict[str, Any]) -> Path | None:
    configured = meta.get("ready_answers", {}).get("file")
    if configured:
        p = profile_path / configured
        return p if p.is_file() else None
    default = profile_path / DEFAULT_READY_ANSWERS
    if default.is_file():
        return default
    for folder in sorted(profile_path.glob("05*")):
        for p in sorted(folder.rglob("*")):
            if p.suffix.lower() in (".md", ".docx") and not _skipped(p.relative_to(profile_path)):
                return p
    return None


class Knowledge:
    """Everything the copilot knows about the candidate, loaded from one profile folder."""

    def __init__(
        self,
        profile: Profile,
        documents: list[Document],
        ready_answers: dict[str, ReadyAnswer],
        vocabulary: list[str],
        replacements: dict[str, str],
        research_domains: list[str],
        ready_answers_file: Path | None = None,
    ):
        self.profile = profile
        self.documents = documents
        self.ready_answers = ready_answers
        self.vocabulary = vocabulary
        self.replacements = replacements
        self.research_domains = research_domains
        self.ready_answers_file = ready_answers_file

    @classmethod
    def load(cls, profile_path: Path) -> Knowledge:
        """Load a profile folder. Missing parts give empty values (``check`` reports them)."""
        profile_path = Path(profile_path).resolve()
        meta = _load_profile_toml(profile_path)
        cand = meta.get("candidate", {})
        profile = Profile(
            path=profile_path,
            name=str(cand.get("name") or "the candidate"),
            target_role=str(cand.get("target_role") or "the role"),
            native_language=str(cand.get("native_language") or "English"),
            meta=meta,
        )
        ra_file = _find_ready_answers_file(profile_path, meta)
        exclude = list(meta.get("ready_answers", {}).get("exclude_headings", []))
        answers = load_ready_answers(ra_file, exclude) if ra_file else []
        replacements = {str(k): str(v) for k, v in meta.get("transcript_replacements", {}).items()}
        domains = [str(d) for d in meta.get("research", {}).get("allowed_domains", [])]
        return cls(
            profile=profile,
            documents=load_documents(profile_path),
            ready_answers={a.id: a for a in answers},
            vocabulary=load_vocabulary(profile_path / "vocabulary.txt"),
            replacements=replacements,
            research_domains=domains,
            ready_answers_file=ra_file,
        )

    def documents_of(self, kind: str) -> list[Document]:
        """Documents of one kind, in load order."""
        return [d for d in self.documents if d.kind == kind]

    def context_block(self) -> str:
        """The static context (sent with prompt caching on every call)."""
        out: list[str] = []
        for kind, tag in SECTIONS:
            docs = self.documents_of(kind)
            if not docs:
                continue
            out.append(f"<{tag}>")
            out += [f'<doc name="{d.path.as_posix()}">\n{d.text}\n</doc>' for d in docs]
            out.append(f"</{tag}>")
        return "\n".join(out)

    def catalog(self) -> str:
        """Ready-answer catalog (``ID | Title`` lines)."""
        return build_catalog(list(self.ready_answers.values()))

    def approx_tokens(self) -> int:
        """Estimated tokens of the cached part (context block + catalog)."""
        return approx_tokens(self.context_block() + "\n" + self.catalog())

    def summary(self) -> str:
        """One-line description used in status bars and logs."""
        n_docs = len(self.documents) - len(self.documents_of("official_docs"))
        n_official = len(self.documents_of("official_docs"))
        return (f"{n_docs} files + {n_official} official docs · ~{self.approx_tokens():,} tokens · "
                f"{len(self.ready_answers)} ready answers · {len(self.vocabulary)} terms")
