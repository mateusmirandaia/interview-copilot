"""CopilotEngine against the local mock API: request shape, ready-answer check, cancel, research."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest

from conftest import DEFAULT_ANSWER, Reply, Request, default_responder
from interview_copilot.ai.engine import (
    CopilotEngine,
    Source,
    extract_sources,
    merge_sources,
    search_error,
)
from interview_copilot.ai.parsing import parse_suggestion
from interview_copilot.knowledge.loader import Knowledge


@pytest.fixture
def engine(mock_api, profile: Path, make_settings) -> CopilotEngine:
    return CopilotEngine(make_settings(profile), Knowledge.load(profile), on_status=lambda s: None)


def ask(engine: CopilotEngine, question: str, timeout: float = 10) -> dict[str, Any]:
    res: dict[str, Any] = {"shown": [], "errors": []}
    done = threading.Event()
    engine.answer(question,
                  on_translation=lambda t: res.__setitem__("translation", t),
                  on_suggestion=res["shown"].append,
                  on_first_content=lambda t: res.__setitem__("first", t),
                  on_suggestion_done=lambda stop: res.__setitem__("stop", stop),
                  on_done=done.set, on_error=res["errors"].append)
    assert done.wait(timeout), "engine did not finish"
    return res


def test_engine_requires_key(monkeypatch: pytest.MonkeyPatch, profile: Path, make_settings):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        CopilotEngine(make_settings(profile), Knowledge.load(profile))


def test_request_shape_and_parallel_translation(engine: CopilotEngine, mock_api):
    res = ask(engine, "How do you use pie test?")
    assert not res["errors"], res["errors"]
    assert res["translation"] == "Pergunta traduzida."
    assert parse_suggestion(res["shown"][-1], True).answer.startswith("I would start")
    assert res["stop"] == "end_turn" and "first" in res

    tr = mock_api.of_kind("translation")[0].body
    sug = mock_api.of_kind("answer")[0].body
    for body in (tr, sug):
        assert body["model"] == "claude-haiku-5-5"
        assert body["stream"] is True
        assert body["output_config"] == {"effort": "low"}
        assert body["thinking"] == {"type": "disabled"}
        assert "temperature" not in body
    assert sug["max_tokens"] == 800 and tr["max_tokens"] == 300
    assert isinstance(tr["system"], str) and "Spanish" in tr["system"]
    assert tr["messages"] == [{"role": "user", "content": "How do you use pytest?"}]   # replacements first
    static = sug["system"][1]
    assert static["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert "<projects>" in static["text"] and "1 | Tell me about yourself" in static["text"]
    assert "cache_control" not in sug["system"][0]
    assert "<interviewer_said>How do you use pytest?</interviewer_said>" in sug["messages"][0]["content"]
    assert engine.stats.cache_read >= 900 and engine.stats.calls == 2
    assert engine.history[-1].question == "How do you use pytest?" and engine.history[-1].check is None


def test_cache_ttl_5m_and_effort_off(mock_api, profile: Path, make_settings):
    s = make_settings(profile, ai={"cache_ttl": "5m", "effort": "", "disable_thinking": False})
    e = CopilotEngine(s, Knowledge.load(profile), on_status=lambda m: None)
    ask(e, "Why are you leaving?")
    body = mock_api.of_kind("answer")[0].body
    assert body["system"][1]["cache_control"] == {"type": "ephemeral"}
    assert "output_config" not in body and "thinking" not in body


def test_history_in_user_message(engine: CopilotEngine, mock_api):
    ask(engine, "First question here?")
    ask(engine, "Second question here?")
    content = mock_api.of_kind("answer")[-1].body["messages"][0]["content"]
    assert "<recent_conversation>\nInterviewer: First question here?" in content
    assert content.endswith("<interviewer_said>Second question here?</interviewer_said>")


def test_warm_cache(engine: CopilotEngine, mock_api):
    statuses: list[str] = []
    engine.on_status = statuses.append
    engine.warm_cache()
    body = mock_api.of_kind("warmup")[0].body
    assert body["max_tokens"] == 1 and "stream" not in body
    assert statuses and statuses[0].startswith("AI ready")


def _ready_responder(check_reply: str):
    def responder(req: Request) -> Reply | str:
        if req.kind == "check":
            return check_reply
        if req.kind == "answer":
            if "NOT allowed" in req.user_text:
                return "READY: NONE\nANSWER: A new answer about queues.\nINTENT: x"
            return Reply(chunks=["READY: ", "1\n", "INTENT: pitch"])
        return default_responder(req)
    return responder


def test_ready_answer_check_yes_shows_it(engine: CopilotEngine, mock_api, tmp_path: Path):
    mock_api.responder = _ready_responder("yes")
    engine.log_path = tmp_path / "sel.jsonl"
    res = ask(engine, "Could you introduce yourself?")
    assert parse_suggestion(res["shown"][-1], True).model_id == "1"
    assert sum("READY: 1" in t for t in res["shown"]) == 1   # held until the check passed, shown once
    check = engine.history[-1].check
    assert check["same_subject"] is True and check["decision"] == "use ready answer"
    assert set(check) == {"time", "question", "ready_answer", "title", "same_subject", "check_reply",
                          "decision", "elapsed_s"}
    req = mock_api.of_kind("check")[0]
    assert req.body["max_tokens"] == 5
    assert "Ready answer title: Tell me about yourself" in req.user_text
    log = [json.loads(x) for x in engine.log_path.read_text(encoding="utf-8").splitlines()]
    assert log[0]["ready_answer"] == "1" and log[0]["same_subject"] is True


def test_ready_answer_check_no_forces_regeneration(engine: CopilotEngine, mock_api, tmp_path: Path):
    mock_api.responder = _ready_responder("no")
    engine.log_path = tmp_path / "sel.jsonl"
    res = ask(engine, "Where did you use message queues?")
    assert all("READY: 1" not in t for t in res["shown"])    # the ready answer never appeared
    assert parse_suggestion(res["shown"][-1], True).answer == "A new answer about queues."
    assert len(mock_api.of_kind("answer")) == 2
    assert "NOT allowed" in mock_api.of_kind("answer")[1].user_text
    check = engine.history[-1].check
    assert check["same_subject"] is False and check["decision"] == "generate new answer"
    assert json.loads(engine.log_path.read_text(encoding="utf-8"))["check_reply"] == "no"


def test_ready_answer_check_disabled(mock_api, profile: Path, make_settings):
    mock_api.responder = _ready_responder("no")
    e = CopilotEngine(make_settings(profile, ai={"check_ready_answers": False}), Knowledge.load(profile),
                      on_status=lambda s: None)
    res = ask(e, "Could you introduce yourself?")
    assert parse_suggestion(res["shown"][-1], True).model_id == "1"
    assert mock_api.of_kind("check") == []


def test_check_error_keeps_ready_answer(engine: CopilotEngine, mock_api, tmp_path: Path):
    engine.log_path = tmp_path / "sel.jsonl"

    def responder(req: Request) -> Reply | str:
        if req.kind == "check":
            return Reply(status=400, error={"type": "invalid_request_error", "message": "bad"})
        return _ready_responder("yes")(req)

    mock_api.responder = responder
    ask(engine, "Introduce yourself please")
    check = engine.history[-1].check
    assert check["same_subject"] is True and check["check_reply"].startswith("error:")


def test_api_error_reported(engine: CopilotEngine, mock_api):
    mock_api.responder = lambda req: Reply(status=400, error={
        "type": "invalid_request_error", "message": "Your credit balance is too low"})
    res = ask(engine, "Anything at all?")
    assert res["stop"] == "error"
    assert any("Suggestion" in e and "credit balance" in e for e in res["errors"])
    assert any(e.startswith("Translation") for e in res["errors"])


def test_cancel(engine: CopilotEngine, mock_api):
    words = DEFAULT_ANSWER.split(" ")
    mock_api.responder = lambda req: Reply(chunks=[w + " " for w in words], delay=0.05)
    res: dict[str, Any] = {"shown": []}
    done = threading.Event()
    started = threading.Event()

    def on_suggestion(t: str) -> None:
        res["shown"].append(t)
        started.set()

    engine.answer("A slow question?", on_translation=lambda t: None, on_suggestion=on_suggestion,
                  on_first_content=lambda t: None, on_suggestion_done=lambda s: res.__setitem__("stop", s),
                  on_done=done.set, on_error=lambda m: None)
    assert started.wait(5)
    engine.cancel()
    n = len(res["shown"])
    assert done.wait(10)
    assert res["stop"] == "cancelled"
    assert len(res["shown"]) <= n + 1
    assert parse_suggestion(res["shown"][-1]).answer != parse_suggestion(DEFAULT_ANSWER, True).answer


def test_suggest_false_only_translates(engine: CopilotEngine, mock_api):
    done = threading.Event()
    engine.answer("Hello there", on_translation=lambda t: None, on_suggestion=lambda t: None,
                  on_first_content=lambda t: None, on_done=done.set, suggest=False)
    assert done.wait(5)
    assert [r.kind for r in mock_api.requests] == ["translation"]


# ---- research --------------------------------------------------------------------------------
def test_research_tool_shape_and_sources(engine: CopilotEngine, mock_api):
    result_block = {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_1", "content": [
        {"type": "web_search_result", "url": "https://docs.python.org/3/a", "title": "A",
         "encrypted_content": "x", "page_age": None},
        {"type": "web_search_result", "url": "https://docs.python.org/3/b", "title": "B",
         "encrypted_content": "x", "page_age": None}]}

    def responder(req: Request) -> Reply | str:
        if req.kind == "research":
            return Reply(blocks=[result_block], text="READY: NONE\nANSWER: The GIL is a lock.\nINTENT: x")
        return default_responder(req)

    mock_api.responder = responder
    res: dict[str, Any] = {}
    done = threading.Event()
    engine.research("What is the GIL in pie test?", on_text=lambda t: None,
                    on_done=lambda raw, stop, src: (res.update(raw=raw, stop=stop, src=src), done.set()),
                    on_error=lambda m: res.__setitem__("err", m))
    assert done.wait(10) and "err" not in res, res
    body = mock_api.of_kind("research")[0].body
    assert body["model"] == "claude-sonnet-5-5"
    assert body["tools"] == [{"type": "web_search_20250305", "name": "web_search", "max_uses": 3,
                              "allowed_domains": ["docs.python.org"]}]
    assert body["max_tokens"] == 1500
    assert "What is the GIL in pytest?" in body["messages"][0]["content"]
    assert "restricted to docs.python.org" in body["messages"][0]["content"]
    assert res["stop"] == "end_turn" and "The GIL is a lock." in res["raw"]
    assert [s.url for s in res["src"]] == ["https://docs.python.org/3/a", "https://docs.python.org/3/b"]


def test_research_search_error(engine: CopilotEngine, mock_api):
    err_block = {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_1",
                 "content": {"type": "web_search_tool_result_error", "error_code": "max_uses_exceeded"}}
    mock_api.responder = lambda req: Reply(blocks=[err_block], text="READY: NONE\nANSWER: ok.")
    res: dict[str, Any] = {"errors": []}
    done = threading.Event()
    engine.research("q?", on_text=lambda t: None, on_done=lambda raw, stop, src: done.set(),
                    on_error=res["errors"].append)
    assert done.wait(10)
    assert any("max_uses_exceeded" in e for e in res["errors"])


def test_research_without_domains(mock_api, profile: Path, make_settings):
    (profile / "profile.toml").write_text('[candidate]\nname = "Sam"\n', encoding="utf-8")
    e = CopilotEngine(make_settings(profile), Knowledge.load(profile), on_status=lambda s: None)
    done = threading.Event()
    e.research("q?", on_text=lambda t: None, on_done=lambda *a: done.set(), on_error=lambda m: None)
    assert done.wait(10)
    assert "allowed_domains" not in mock_api.of_kind("research")[0].body["tools"][0]


def test_extract_sources_and_helpers():
    content = [
        {"type": "server_tool_use", "name": "web_search"},
        {"type": "web_search_tool_result", "content": [
            {"type": "web_search_result", "url": "https://a", "title": "A"},
            {"type": "web_search_result", "url": "https://b", "title": "B"},
            {"type": "web_search_result", "url": "https://c", "title": ""},
            {"type": "web_search_result", "url": "https://d", "title": "D"}]},
        {"type": "text", "text": "point", "citations": [
            {"type": "web_search_result_location", "url": "https://b", "title": "B"},
            {"type": "web_search_result_location", "url": "https://b", "title": "B"}]},
    ]
    assert [s.url for s in extract_sources(content)] == ["https://b"]            # citations win
    found = extract_sources(content[:2])
    assert [s.url for s in found] == ["https://a", "https://b", "https://c"]     # else the first 3
    assert found[2].title == "https://c"
    assert extract_sources(None) == []
    merged = merge_sources([Source("A", "https://a")], [Source("A2", "https://a"), Source("Z", "https://z")])
    assert [s.url for s in merged] == ["https://a", "https://z"]
    err = [{"type": "web_search_tool_result", "content": {"type": "web_search_tool_result_error",
                                                          "error_code": "too_many_requests"}}]
    assert search_error(err) == "web search tool error: too_many_requests"
    assert search_error(content) is None
