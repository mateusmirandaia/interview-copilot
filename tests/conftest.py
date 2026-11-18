"""Shared fixtures: a local mock of the Anthropic Messages API and temporary profiles/settings.

Everything runs offline: the Anthropic client is pointed at the mock with ``ANTHROPIC_BASE_URL``.
"""

from __future__ import annotations

import json
import os
import threading
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from interview_copilot.settings import Settings, deep_merge

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PROFILE = ROOT / "profiles" / "example"
LOCAL_HOSTS = "127.0.0.1,localhost"

# the mock must never be reached through an HTTP proxy
for _var in ("NO_PROXY", "no_proxy"):
    _current = os.environ.get(_var, "")
    if "127.0.0.1" not in _current:
        os.environ[_var] = f"{_current},{LOCAL_HOSTS}" if _current else LOCAL_HOSTS


# ---------------------------------------------------------------------------------------------
# Mock Anthropic API
# ---------------------------------------------------------------------------------------------
@dataclass
class Reply:
    """What the mock answers to one request.

    - ``text``: a text reply (streamed in ``chunks`` when the request has ``stream: true``);
    - ``blocks``: raw content blocks (e.g. ``web_search_tool_result``), sent before the text;
    - ``status`` + ``error``: an API error (``{"type": ..., "message": ...}``);
    - ``json``: a raw JSON body (e.g. for ``/v1/messages/count_tokens``);
    - ``delay``: seconds to wait between streamed chunks.
    """

    text: str = ""
    chunks: list[str] | None = None
    blocks: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str = "end_turn"
    status: int = 200
    error: dict[str, str] | None = None
    json: dict[str, Any] | None = None
    delay: float = 0.0
    usage: dict[str, int] = field(default_factory=lambda: {
        "input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 900,
        "cache_creation_input_tokens": 0})


@dataclass
class Request:
    """A request received by the mock."""

    path: str
    body: dict[str, Any]
    headers: dict[str, str]

    @property
    def system_text(self) -> str:
        """The system prompt as one string (first block when it is a list)."""
        s = self.body.get("system", "")
        if isinstance(s, list):
            return "\n".join(b.get("text", "") for b in s)
        return s or ""

    @property
    def user_text(self) -> str:
        """Content of the last user message (text only)."""
        msgs = [m for m in self.body.get("messages", []) if m.get("role") == "user"]
        if not msgs:
            return ""
        c = msgs[-1]["content"]
        return c if isinstance(c, str) else " ".join(b.get("text", "") for b in c if isinstance(b, dict))

    @property
    def kind(self) -> str:
        """translation | check | judge | suggestions | research | count_tokens | warmup | answer"""
        if self.path.endswith("/count_tokens"):
            return "count_tokens"
        st = self.system_text
        if st.startswith("Translate"):
            return "translation"
        if st.startswith("You check"):
            return "check"
        if st.startswith("You are a strict evaluator"):
            return "judge"
        if st.startswith("You review the results"):
            return "suggestions"
        if self.body.get("tools"):
            return "research"
        if self.body.get("max_tokens") == 1:
            return "warmup"
        return "answer"


Responder = Callable[[Request], "Reply | str"]

DEFAULT_ANSWER = ("READY: NONE\nANSWER: I would start by measuring the slow part with a profiler, then fix "
                  "the biggest cost first.\nINTENT: saber se você mede antes de otimizar")
DEFAULT_JUDGE = json.dumps({
    "scores": {"correctness": 2, "real_cases": 2, "simplicity": 2, "focus": 2, "speakable": 2,
               "answers_question": 2},
    "failed": False, "fail_reason": "", "summary": "ok", "problems": [],
    "numbers": [], "understood_question": True})


def default_responder(req: Request) -> Reply | str:
    """Plausible replies for every kind of call the app makes."""
    kind = req.kind
    if kind == "count_tokens":
        return Reply(json={"input_tokens": 4321})
    if kind == "translation":
        return "Pergunta traduzida."
    if kind == "check":
        return "yes"
    if kind == "judge":
        return DEFAULT_JUDGE
    if kind == "suggestions":
        return "- Keep answers shorter (ids 1, 2)."
    if kind == "warmup":
        return "ok"
    return DEFAULT_ANSWER


def _message(text: str, blocks: list[dict[str, Any]], reply: Reply, model: str) -> dict[str, Any]:
    content = list(blocks) + ([{"type": "text", "text": text}] if text or not blocks else [])
    return {"id": "msg_mock", "type": "message", "role": "assistant", "model": model, "content": content,
            "stop_reason": reply.stop_reason, "stop_sequence": None, "usage": reply.usage}


def _sse_events(reply: Reply, model: str) -> list[tuple[str, dict[str, Any]]]:
    usage = dict(reply.usage, output_tokens=0)
    evs: list[tuple[str, dict[str, Any]]] = [("message_start", {"type": "message_start", "message": {
        "id": "msg_mock", "type": "message", "role": "assistant", "model": model, "content": [],
        "stop_reason": None, "stop_sequence": None, "usage": usage}})]
    index = 0
    for block in reply.blocks:
        evs.append(("content_block_start", {"type": "content_block_start", "index": index,
                                            "content_block": block}))
        evs.append(("content_block_stop", {"type": "content_block_stop", "index": index}))
        index += 1
    chunks = reply.chunks if reply.chunks is not None else ([reply.text] if reply.text else [])
    if chunks:
        evs.append(("content_block_start", {"type": "content_block_start", "index": index,
                                            "content_block": {"type": "text", "text": ""}}))
        for piece in chunks:
            evs.append(("content_block_delta", {"type": "content_block_delta", "index": index,
                                                "delta": {"type": "text_delta", "text": piece}}))
        evs.append(("content_block_stop", {"type": "content_block_stop", "index": index}))
    evs += [("message_delta", {"type": "message_delta",
                               "delta": {"stop_reason": reply.stop_reason, "stop_sequence": None},
                               "usage": {"output_tokens": reply.usage.get("output_tokens", 5)}}),
            ("message_stop", {"type": "message_stop"})]
    return evs


class MockAnthropic:
    """Local HTTP server speaking enough of the Messages API for the SDK (JSON and SSE)."""

    def __init__(self, responder: Responder = default_responder):
        self.responder = responder
        self.requests: list[Request] = []
        self._lock = threading.Lock()
        mock = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self) -> None:  # noqa: N802 - http.server API
                length = int(self.headers.get("content-length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                req = Request(self.path.split("?")[0], body, {k.lower(): v for k, v in self.headers.items()})
                with mock._lock:
                    mock.requests.append(req)
                reply = mock.responder(req)
                if isinstance(reply, str):
                    reply = Reply(text=reply)
                model = str(body.get("model", "mock-model"))
                if reply.status != 200:
                    err = reply.error or {"type": "api_error", "message": "mock error"}
                    self._send(reply.status, "application/json",
                               json.dumps({"type": "error", "error": err}).encode())
                    return
                if reply.json is not None:
                    self._send(200, "application/json", json.dumps(reply.json).encode())
                    return
                if not body.get("stream"):
                    self._send(200, "application/json",
                               json.dumps(_message(reply.text, reply.blocks, reply, model)).encode())
                    return
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.send_header("cache-control", "no-cache")
                self.send_header("connection", "close")
                self.end_headers()
                for name, data in _sse_events(reply, model):
                    if reply.delay and name == "content_block_delta":
                        time.sleep(reply.delay)
                    try:
                        self.wfile.write(f"event: {name}\ndata: {json.dumps(data)}\n\n".encode())
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        return
                self.close_connection = True

            def _send(self, status: int, ctype: str, data: bytes) -> None:
                self.send_response(status)
                self.send_header("content-type", ctype)
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args: Any) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05},
                                       daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def of_kind(self, kind: str) -> list[Request]:
        """Requests of one kind (see :attr:`Request.kind`)."""
        with self._lock:
            return [r for r in self.requests if r.kind == kind]

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def mock_api(monkeypatch: pytest.MonkeyPatch):
    """A running mock; ``ANTHROPIC_API_KEY`` and ``ANTHROPIC_BASE_URL`` point the SDK at it."""
    mock = MockAnthropic()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", mock.url)
    yield mock
    mock.close()


# ---------------------------------------------------------------------------------------------
# Settings and profiles
# ---------------------------------------------------------------------------------------------
def default_raw() -> dict[str, Any]:
    with open(ROOT / "config" / "settings.toml", "rb") as f:
        return tomllib.load(f)


@pytest.fixture
def make_settings(tmp_path: Path):
    """Factory: ``make_settings(profile_path, **section_overrides)`` -> Settings rooted at tmp_path.

    Logs go to ``tmp_path/logs`` so tests never write into the repository.
    """
    def factory(profile: Path = EXAMPLE_PROFILE, **sections: dict[str, Any]) -> Settings:
        raw = deep_merge(default_raw(), sections)
        raw["profile"] = {"path": str(Path(profile).resolve())}
        return Settings(raw, root=tmp_path)

    return factory


PROJECTS_MD = """# Projects - Sam Lee

## Topic → case map

| Topic | Case |
|---|---|
| Queues | Order queue |
| Caching | Cache rollout |

## Order queue

- **Company:** Acme Corp (2022).
- **Keywords:** order queue, RabbitMQ
- **Result:** 30% fewer timeouts.

## Cache rollout

- **Company:** Globex (2021).
- **Keywords:** cache rollout, Memcached
- **Result:** p95 from 800 ms to 90 ms.
"""

READY_MD = """# Ready answers

## Tell me about yourself
I'm Sam. I have six years of Go and Python.
Tip: keep it short.

## Why are you leaving?
I want a bigger scope.

```
## not a heading inside a fence
```

## Internal notes
Never shown.
"""

QUESTIONS = {
    "description": "test set",
    "facts": ["Sam has six years of experience."],
    "auto_fail": ["Claims Kubernetes cluster operation."],
    "questions": [
        {"id": 1, "category": "Behavioral", "question": "Tell me about yourself.",
         "must_contain": [{"term": "six years", "alternatives": ["6 years"]}],
         "must_not_contain": [{"description": "invented employer", "words": ["Google"]}],
         "equivalent_to": None},
        {"id": 2, "category": "Technical", "question": "How do you handle slow queues?",
         "must_contain": [{"term": "RabbitMQ", "alternatives": []}],
         "must_not_contain": [], "equivalent_to": None},
        {"id": "V1", "category": "Transcription variant", "question": "Tell me about your shelf.",
         "must_contain": [], "must_not_contain": [], "equivalent_to": 1},
    ],
}


def build_profile(root: Path) -> Path:
    """Write a small but complete profile under ``root`` and return its path."""
    p = root / "profile"
    files = {
        "profile.toml": ('[candidate]\nname = "Sam Lee"\ntarget_role = "Backend Engineer"\n'
                         'native_language = "Spanish"\n\n[ready_answers]\n'
                         'file = "05-ready-answers/ready-answers.md"\n'
                         'exclude_headings = ["Internal notes"]\n\n'
                         '[research]\nallowed_domains = ["docs.python.org"]\n\n'
                         '[transcript_replacements]\n"pie test" = "pytest"\n'),
        "01-instructions/instructions.md": "# Instructions\nBe brief.",
        "02-resume/resume.md": "# Resume\nSam Lee, six years.",
        "03-projects/projects.md": PROJECTS_MD,
        "04-skills/python.md": "# Python\nGIL notes.",
        "04-skills/sub/go.md": "# Go\nGoroutines.",
        "04-skills/_draft.md": "DRAFT",
        "04-skills/.hidden.md": "HIDDEN",
        "04-skills/image.png": "PNG",
        "05-ready-answers/ready-answers.md": READY_MD,
        "06-job/job.md": "# Job\nGlobex backend role.",
        "07-official-docs/links.txt": "# docs\nhttps://docs.python.org/3/library/asyncio.html\n",
        "07-official-docs/01 - asyncio.md": "# asyncio\nSource: https://docs.python.org\nEvent loop.",
        "notes/ignored.md": "NOT NUMBERED",
        "vocabulary.txt": "# names\nSam Lee\nC#\nRabbitMQ  # broker\nRabbitMQ\n",
        "evals/questions.json": json.dumps(QUESTIONS),
    }
    for rel, text in files.items():
        f = p / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    (p / "04-skills" / "~$lock.md").write_text("LOCK", encoding="utf-8")
    return p


@pytest.fixture
def profile(tmp_path: Path) -> Path:
    """A temporary profile (see :func:`build_profile`)."""
    return build_profile(tmp_path)
