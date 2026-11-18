"""Evals: keyword and automatic checks, judge helpers, end-to-end rounds against the mock API."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from conftest import DEFAULT_JUDGE, EXAMPLE_PROFILE, PROJECTS_MD, Reply, Request, default_responder
from interview_copilot.evals import judge as judge_mod
from interview_copilot.evals import report as report_mod
from interview_copilot.evals import runner

LONG_TWO_CASES = ("At Acme I moved the order queue to RabbitMQ so slow consumers stopped blocking the API. "
                  "Later, at Globex, the cache rollout with Memcached cut the p95 from 800 ms to 90 ms. "
                  + "I always measure first and then fix the biggest cost, step by step, with tests. " * 4)


# ---- text checks -----------------------------------------------------------------------------
def test_norm_and_contains():
    tn = runner.norm("I’m using “FastAPI” — and SQS, not JavaScript.")
    assert tn == "i'm using \"fastapi\" - and sqs, not javascript."
    assert runner.contains(tn, "fastapi") and runner.contains(tn, "I'm")
    assert runner.contains(tn, "SQS")
    assert not runner.contains(tn, "Java ")          # short term: whole word only
    assert not runner.contains(tn, "QS")
    assert not runner.contains(tn, "  ")
    assert runner.contains(runner.norm("Moved to C# last year"), "C#")


def test_keyword_check():
    item = {"must_contain": [{"term": "8 years", "alternatives": ["eight years"]},
                             {"term": "FastAPI", "alternatives": []},
                             {"term": "Django", "alternatives": ["DRF"]}],
            "must_not_contain": [{"description": "invented employer", "words": ["Google", "Meta"]},
                                 {"description": "judge only"}]}
    kw = runner.keyword_check("I have eight years with FastAPI; before that, Google.", item)
    assert kw["missing"] == ["Django"]
    assert kw["forbidden"] == ["invented employer (Google)"]
    assert kw["coverage"] == pytest.approx(2 / 3)
    assert runner.keyword_check("anything", {})["coverage"] == 1.0


def test_parse_and_detect_cases():
    cases = runner.parse_cases(PROJECTS_MD)
    assert [(c.name, c.keywords) for c in cases] == [("Order queue", ["order queue", "RabbitMQ"]),
                                                    ("Cache rollout", ["cache rollout", "Memcached"])]
    assert runner.detect_cases("We used rabbitmq there.", cases) == ["Order queue"]
    assert runner.detect_cases(LONG_TWO_CASES, cases) == ["Order queue", "Cache rollout"]
    assert runner.detect_cases("Nothing relevant.", cases) == []
    md = "## Topic -> case\n| a | b |\n## Plain case\nno keywords\n# Other title\n- **Keywords:** orphan\n"
    assert [(c.name, c.keywords) for c in runner.parse_cases(md)] == [("Plain case", [])]


def test_word_count_and_limits():
    assert runner.word_count("I’m Sam, with 8 years of C# and F&O.") == 9
    pitch = {"id": 7, "category": "Behavioral", "question": "Tell me about yourself."}
    assert runner.is_pitch({"id": 1, "category": "Technical", "question": "x"})
    assert runner.is_pitch(pitch) and runner.is_pitch({"id": 3, "category": "Pitch", "question": "x"})
    other = {"id": 9, "category": "Technical", "question": "What is the GIL?"}
    assert not runner.is_pitch(other)
    assert runner.is_pitch(other, {"type": "ready answer", "ready_answer": "Introduction pitch"})
    assert runner.word_limit(pitch, {}, 80, 120) == 120 and runner.word_limit(other, {}, 80, 120) == 80
    cases = runner.parse_cases(PROJECTS_MD)
    checks = runner.auto_checks(other, {"shown": LONG_TWO_CASES, "words": 90}, cases, 80, 100)
    assert checks == {"cases": ["Order queue", "Cache rollout"], "more_than_one_case": True, "word_limit": 80,
                      "over_limit": True}


def test_verdict_reasons():
    base = {"gen": {"type": "generated", "errors": []},
            "keywords": {"missing": [], "forbidden": [], "coverage": 1.0},
            "checks": {"cases": [], "more_than_one_case": False}}
    r = json.loads(json.dumps(base))
    runner.verdict(r)
    assert r["failed"] is False and r["reason"] == "ok"
    r = json.loads(json.dumps(base))
    r["keywords"]["missing"] = ["FastAPI"]
    r["judge"] = {"summary": "ok"}
    runner.verdict(r)
    assert r["failed"] is False and r["reason"] == "missing: FastAPI"
    r = json.loads(json.dumps(base))
    r["checks"] = {"cases": ["A", "B"], "more_than_one_case": True}
    r["judge"] = {"failed": True, "fail_reason": "invented number"}
    r["gen"] = {"type": "empty", "errors": ["Suggestion: boom"]}
    runner.verdict(r)
    assert r["failed"] is True
    assert r["reason"] == "more than one real case: A, B; invented number; no answer (Suggestion: boom)"


# ---- judge helpers ---------------------------------------------------------------------------
def test_normalize_verdict_and_parse_json():
    j = judge_mod.normalize_verdict({"scores": {"correctness": 5, "focus": -1, "speakable": "1"},
                                     "problems": ["too_long", "made_up_tag"],
                                     "numbers": [{"number": "30%", "source": "projects.md"}, "bad"]})
    assert j["scores"] == {"correctness": 2, "real_cases": 0, "simplicity": 0, "focus": 0, "speakable": 1,
                           "answers_question": 0}
    assert j["total"] == 3 and j["problems"] == ["too_long"] and len(j["numbers"]) == 1
    assert j["understood_question"] is True and j["failed"] is False
    assert judge_mod.parse_json('Here: {"a": {"b": 1}} done') == {"a": {"b": 1}}
    with pytest.raises(ValueError, match="did not return JSON"):
        judge_mod.parse_json("no json")


def _client(mock_api, retries: int = 0):
    import anthropic

    return anthropic.Anthropic(api_key="test", base_url=mock_api.url, max_retries=retries)


USER_X = [{"role": "user", "content": "x"}]
NUMBER = {"number": "800 ms", "source": "03-projects/projects.md"}
CREDIT = {"type": "invalid_request_error",
          "message": "Your credit balance is too low to access the Anthropic API."}


def test_describe_api_error(mock_api):
    import anthropic

    mock_api.responder = lambda req: Reply(status=400, error=CREDIT)
    with pytest.raises(anthropic.APIStatusError) as exc:
        _client(mock_api).messages.create(model="m", max_tokens=5, messages=USER_X)
    text = judge_mod.describe_api_error(exc.value)
    assert text.startswith("400 invalid_request_error — check your credit balance: Your credit balance")
    assert not judge_mod.is_retryable(exc.value)
    auth = {"type": "authentication_error", "message": "bad key"}
    mock_api.responder = lambda req: Reply(status=401, error=auth)
    with pytest.raises(anthropic.APIStatusError) as exc:
        _client(mock_api).messages.create(model="m", max_tokens=5, messages=USER_X)
    expected = "401 authentication_error — check ANTHROPIC_API_KEY: bad key"
    assert judge_mod.describe_api_error(exc.value) == expected
    assert judge_mod.describe_api_error(ValueError("x")) == "ValueError: x"


def _item(qid: Any = 1) -> dict[str, Any]:
    return {"id": qid, "category": "Behavioral", "question": "Tell me about yourself.",
            "must_contain": [{"term": "six years"}],
            "must_not_contain": [{"description": "d", "words": ["G"]}]}


def test_judge_retries_then_succeeds(mock_api):
    calls = []

    def responder(req: Request) -> Reply | str:
        calls.append(req)
        return Reply(status=500, error={"type": "api_error", "message": "boom"}) if len(calls) < 3 \
            else DEFAULT_JUDGE

    mock_api.responder = responder
    j = judge_mod.Judge(_client(mock_api), "judge-m", [{"type": "text", "text": "S"}], retry_pause_s=0)
    out = j(_item(), {"shown": "I'm Sam.", "type": "ready answer", "words": 2},
            {"question": "Tell me about yourself."})
    assert out["total"] == 12 and len(calls) == 3
    payload = json.loads(calls[-1].user_text)
    assert payload["copilot_answer_shown"] == "I'm Sam." and payload["must_not_contain"] == ["d (G)"]
    assert payload["equivalent_to_question"] == "Tell me about yourself." and "note" in payload
    assert calls[-1].body["model"] == "judge-m" and "stream" not in calls[-1].body


def test_judge_gives_up_after_two_retries(mock_api):
    mock_api.responder = lambda req: "not json at all"
    j = judge_mod.Judge(_client(mock_api), "m", [], retry_pause_s=0)
    assert "did not return JSON" in j(_item(), {})["error"]
    assert len(mock_api.requests) == 3


def test_judge_fatal_error_stops_further_calls(mock_api):
    mock_api.responder = lambda req: Reply(status=400, error=CREDIT)
    j = judge_mod.Judge(_client(mock_api), "m", [], retry_pause_s=0)
    first = j(_item(1), {})
    second = j(_item(2), {})
    assert "check your credit balance" in first["error"] and second == first
    assert len(mock_api.requests) == 1 and j.fatal


# ---- end to end ------------------------------------------------------------------------------
def _question_of(req: Request) -> str:
    m = re.search(r"<interviewer_said>(.*?)</interviewer_said>", req.user_text, re.S)
    return m.group(1) if m else req.user_text


def make_responder(judge_scores: dict[str, int] | None = None, judge_status: int = 200):
    """Answers per question + judge verdicts per id."""
    def responder(req: Request) -> Reply | str:
        kind = req.kind
        if kind == "answer":
            q = _question_of(req)
            if "NOT allowed" in req.user_text:
                return ("READY: NONE\nANSWER: I have six years of Go and Python, mostly backend APIs.\n"
                        "INTENT: x")
            if "yourself" in q or "shelf" in q:
                return "READY: 1\nINTENT: apresentação"
            if "queues" in q:
                return f"READY: NONE\nANSWER: {LONG_TWO_CASES}\nINTENT: filas"
        if kind == "check":
            return "no" if "shelf" in req.user_text else "yes"
        if kind == "judge":
            if judge_status != 200:
                return Reply(status=judge_status, error=CREDIT)
            payload = json.loads(req.user_text)
            qid = str(payload["id"])
            score = (judge_scores or {}).get(qid, 2)
            verdict = {"scores": {k: score for k, _ in judge_mod.CRITERIA}, "failed": qid == "2",
                       "fail_reason": "mixes two cases" if qid == "2" else "",
                       "summary": "ok" if qid != "2" else "two cases", "problems":
                       ["more_than_one_case", "too_long"] if qid == "2" else [],
                       "numbers": [NUMBER] if qid == "2" else [],
                       "understood_question": qid != "V1"}
            return json.dumps(verdict)
        return default_responder(req)
    return responder


def run_round(settings, *args: str) -> tuple[int, list[str]]:
    lines: list[str] = []
    code = runner.main(list(args), settings, out=lines.append, judge_retry_pause_s=0)
    return code, lines


def test_full_round(mock_api, profile: Path, make_settings, tmp_path: Path):
    (profile / "evals" / "notes.md").write_text("Pre-analysis: answers run long.", encoding="utf-8")
    mock_api.responder = make_responder()
    settings = make_settings(profile)
    code, lines = run_round(settings, "--round", "t1", "--ids", "1,2,V1", "--parallel", "2")
    assert code == 0, lines
    folder = tmp_path / "logs" / "evals"
    data = json.loads((folder / "results_t1.json").read_text(encoding="utf-8"))
    assert data["round"] == "t1" and data["judge_model"] == "claude-sonnet-5-5"
    res = data["results"]
    assert set(res) == {"1", "2", "V1"}

    r1 = res["1"]
    assert r1["gen"]["type"] == "ready answer" and r1["gen"]["ready_answer"] == "Tell me about yourself"
    assert r1["gen"]["shown"] == "I'm Sam. I have six years of Go and Python."
    assert r1["gen"]["ready_check"]["same_subject"] is True
    assert r1["gen"]["translation"] == "Pergunta traduzida."
    assert r1["keywords"]["missing"] == [] and r1["checks"]["word_limit"] == 100
    assert r1["failed"] is False and r1["reason"] == "ok" and r1["judge"]["total"] == 12
    for key in ("ttft_s", "first_content_s", "total_s"):
        assert isinstance(r1["gen"][key], float)

    r2 = res["2"]
    assert r2["checks"]["more_than_one_case"] and r2["checks"]["over_limit"]
    assert r2["failed"] and "more than one real case: Order queue, Cache rollout" in r2["reason"]
    assert "mixes two cases" in r2["reason"]

    rv = res["V1"]
    assert rv["gen"]["type"] == "generated" and rv["gen"]["ready_check"]["same_subject"] is False
    assert rv["judge"]["understood_question"] is False

    # every question isolated (history cleared) and the selection log kept with the round
    for req in mock_api.of_kind("answer"):
        assert "<recent_conversation>" not in req.user_text
    log = (folder / "answer_selection_t1.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(log) == 2

    # the judge prompt: rubric, generic + profile rules, facts, projects, full context, cached
    jreq = mock_api.of_kind("judge")[0]
    system = jreq.body["system"]
    assert system[0]["cache_control"] == {"type": "ephemeral"}
    text = system[0]["text"]
    assert "Sam Lee" in text and "about 70 words and never more than 80" in text and "up to 100" in text
    assert "Claims Kubernetes cluster operation." in text and "Sam has six years of experience." in text
    assert "## Order queue" in text and "<official_docs>" in text and "Event loop." in text
    assert "mixes two or more real cases" in text and "too_long" in text
    assert '"answers_question": 0-2' in text and "{{" not in text
    assert jreq.body["model"] == "claude-sonnet-5-5"
    assert len(mock_api.of_kind("judge")) == 3 and len(mock_api.of_kind("suggestions")) == 1

    report = (folder / "report_t1.md").read_text(encoding="utf-8")
    for heading in ("# Eval report · round t1", "## Automatic checks (should all be zero)",
                    "## Answer length (limit: 80 words; introduction pitch: 100)", "## 1. Summary",
                    "## 2. All questions", "## 3. Worst 10", "## 4. Recurring problems",
                    "## 5. Suggestions for the prompt or the profile (not applied)",
                    "## 6. Transcription variants", "## 7. Numbers cited and their source"):
        assert heading in report, heading
    assert "Comparison with the previous round" not in report
    assert "| Answers with more than one real case | 1 | 2 (Order queue, Cache rollout) |" in report
    assert f"| Answers over the word limit | 1 | 2 ({r2['gen']['words']} words) |" in report
    assert "1 used, 1 rejected" in report
    assert "| V1 | Tell me about your shelf. | Tell me about yourself |" in report
    assert "**Passed:** 2 of 3 · **Failed:** 1" in report
    assert f"{r2['gen']['words']} ⚠" in report
    assert "### 2 · How do you handle slow queues?" in report
    assert report.index("### 2 ·") < report.index("### 1 ·")              # failed first in the worst list
    assert "Pre-analysis: answers run long." in report and "- Keep answers shorter" in report
    assert "| V1 | Tell me about your shelf. | 1 | no | 12 | 12 | no |" in report
    assert "| 2 | 800 ms | 03-projects/projects.md |" in report
    assert "mixes more than one real case in the same answer:** 1 question(s) (2)" in report
    assert "`logs/evals/results_t1.json`" in report
    assert any("Passed 2 of 3" in line for line in lines)


def test_no_judge_and_rejudge(mock_api, profile: Path, make_settings, tmp_path: Path):
    mock_api.responder = make_responder()
    settings = make_settings(profile)
    code, _ = run_round(settings, "--round", "nj", "--no-judge")
    assert code == 0
    assert mock_api.of_kind("judge") == [] and mock_api.of_kind("suggestions") == []
    folder = tmp_path / "logs" / "evals"
    data = json.loads((folder / "results_nj.json").read_text(encoding="utf-8"))
    assert data["judge_model"] is None and all("judge" not in r for r in data["results"].values())
    assert data["results"]["2"]["failed"] and not data["results"]["1"]["failed"]
    report = (folder / "report_nj.md").read_text(encoding="utf-8")
    assert "judge: `none (--no-judge)`" in report and "(no suggestions generated)" in report

    answers_before = len(mock_api.of_kind("answer"))
    code, _ = run_round(settings, "--round", "nj", "--rejudge", "--judge-model", "other-judge")
    assert code == 0
    assert len(mock_api.of_kind("answer")) == answers_before          # answers reused
    assert {r.body["model"] for r in mock_api.of_kind("judge")} == {"other-judge"}
    data = json.loads((folder / "results_nj.json").read_text(encoding="utf-8"))
    assert all("total" in r["judge"] for r in data["results"].values())


def test_compare_two_rounds(mock_api, profile: Path, make_settings, tmp_path: Path):
    settings = make_settings(profile)
    mock_api.responder = make_responder({"1": 2, "2": 1, "V1": 2})
    assert run_round(settings, "--round", "r1")[0] == 0
    folder = tmp_path / "logs" / "evals"
    first = (folder / "results_r1.json").read_text(encoding="utf-8")
    mock_api.responder = make_responder({"1": 1, "2": 2, "V1": 2})
    code, lines = run_round(settings, "--round", "r2", "--compare-with", "results_r1.json")
    assert code == 0
    assert (folder / "results_r1.json").read_text(encoding="utf-8") == first   # never overwritten
    report = (folder / "report_r2.md").read_text(encoding="utf-8")
    section = report.split("## Comparison with the previous round (`results_r1.json`)")[1].split("\n## ")[0]
    assert "| Passed | 2 of 3 | 2 of 3 |" in section
    assert "| Average total (of 12) | 10.0 | 10.0 |" in section          # (12+6+12)/3 both times
    assert "**Improved:** 1" in section and "**Worsened:** 1" in section
    assert "| 1 | Tell me about yourself. | 12 → 6 | no → no |" in section
    assert "| 2 | How do you handle slow queues? | 6 → 12 | yes → yes |" in section
    # a missing file or this round's own file gives a warning, not a crash
    assert run_round(settings, "--round", "r3", "--compare-with", "nope.json", "--no-judge")[0] == 0
    code, lines = run_round(settings, "--round", "r3", "--compare-with", "results_r3.json", "--no-judge")
    assert any("own results" in line for line in lines)


def test_judge_api_error_is_surfaced(mock_api, profile: Path, make_settings, tmp_path: Path):
    mock_api.responder = make_responder(judge_status=400)
    code, lines = run_round(make_settings(profile), "--round", "err", "--ids", "1")
    assert code == 0
    expected = "[error] judge: 400 invalid_request_error — check your credit balance"
    assert any(expected in line for line in lines)
    assert mock_api.of_kind("suggestions") == []
    report = (tmp_path / "logs" / "evals" / "report_err.md").read_text(encoding="utf-8")
    assert "**Judge errors:** 1 (400 invalid_request_error — check your credit balance" in report


def test_generation_error_stops_early(mock_api, profile: Path, make_settings):
    mock_api.responder = lambda req: Reply(status=400, error=CREDIT) if req.kind == "answer" \
        else default_responder(req)
    code, lines = run_round(make_settings(profile), "--round", "gen-err")
    assert code == 1 and any("the first question failed" in line for line in lines)
    assert len(mock_api.of_kind("answer")) == 1


def test_runner_input_errors(mock_api, profile: Path, make_settings, tmp_path: Path, monkeypatch):
    settings = make_settings(profile)
    assert run_round(settings, "--ids", "999")[0] == 1
    code, lines = run_round(settings, "--round", "never-run", "--rejudge")
    assert code == 1 and "no saved answers" in lines[-1]
    (profile / "evals" / "questions.json").unlink()
    code, lines = run_round(settings)
    assert code == 1 and "Eval questions not found" in lines[-1]
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    (profile / "evals" / "questions.json").write_text('{"questions": [{"id": 1, "question": "q"}]}')
    code, lines = run_round(settings)
    assert code == 1 and "ANTHROPIC_API_KEY" in lines[-1]


def test_example_profile_subset(mock_api, make_settings, tmp_path: Path):
    """The shipped example profile and questions work end to end (ids 1 and 23, no judge)."""
    answers = {"Tell me about yourself.": "READY: 1\nINTENT: x",
               "How much Kubernetes experience do you have?":
                   "READY: NONE\nANSWER: Only basic usage. At Contoso Logistics our tracking API ran "
                   "with Helm charts, and the CI pipeline deployed to ECS.\nINTENT: x"}

    def responder(req: Request) -> Reply | str:
        if req.kind == "answer":
            return answers.get(_question_of(req), "READY: NONE\nANSWER: ok\nINTENT: x")
        return default_responder(req)

    mock_api.responder = responder
    code, _ = run_round(make_settings(EXAMPLE_PROFILE), "--round", "ex", "--ids", "1,23", "--no-judge")
    assert code == 0
    res = json.loads((tmp_path / "logs" / "evals" / "results_ex.json").read_text(encoding="utf-8"))["results"]
    assert res["1"]["gen"]["type"] == "ready answer" and res["1"]["checks"]["word_limit"] == 100
    assert res["23"]["checks"]["cases"] == ["Tracking API latency", "CI pipeline speed-up"]
    assert res["23"]["failed"]


def test_report_helpers():
    assert report_mod.mean([1, None, 2]) == 1.5 and report_mod.mean([]) is None
    assert report_mod.fmt(None) == "–" and report_mod.fmt(1.5, " s") == "1.5 s"
    assert report_mod.one_line("a |\n b", 50) == "a / b"
    assert report_mod.one_line("x" * 20, 10) == "x" * 9 + "…"
