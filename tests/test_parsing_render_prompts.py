"""Output parsing, rendering and the generic system prompt."""

from __future__ import annotations

from pathlib import Path

from interview_copilot.ai.parsing import parse_suggestion
from interview_copilot.ai.prompts import (
    CHECK_SYSTEM,
    FORCE_NEW_ANSWER,
    TRANSLATE_SYSTEM,
    build_research_request,
    build_system_prompt,
    build_translate_system,
    fill,
)
from interview_copilot.knowledge.loader import Knowledge
from interview_copilot.knowledge.ready_answers import ReadyAnswer
from interview_copilot.render import KINDS, answer_parts


# ---- parsing ---------------------------------------------------------------------------------
def test_parse_all_markers():
    s = parse_suggestion("READY: NONE\nANSWER: First I measure.\nThen I fix it.\nADD: extra\n"
                         "DOCS: a doc diz outra coisa\nINTENT: medir antes", complete=True)
    assert s.model_id is None and s.model_decided
    assert s.answer == "First I measure. Then I fix it."   # continuation lines join the field
    assert s.add == "extra" and s.docs == "a doc diz outra coisa" and s.intent == "medir antes"
    assert s.has_content and not s.no_question


def test_parse_ready_and_v1_aliases():
    s = parse_suggestion("MODEL: 3c\nADD: I also used queues.\nQUER SABER: experiência", complete=True)
    assert s.model_id == "3c" and s.add == "I also used queues." and s.intent == "experiência"
    s = parse_suggestion("ready: 7\nintent: x", complete=True)   # case-insensitive keys
    assert s.model_id == "7" and s.intent == "x"
    assert parse_suggestion("READY:\n", complete=True).model_id is None


def test_parse_partial_streaming():
    assert parse_suggestion("READY: 3").model_id is None            # line not finished yet
    assert parse_suggestion("READY: 3").model_decided is False
    assert parse_suggestion("READY: 3", complete=True).model_id == "3"
    assert parse_suggestion("READY: 3c\n").model_id == "3c"
    assert parse_suggestion("READY: NONE\nANSWER: I wo").answer == "I wo"
    assert parse_suggestion("NO_QUES").no_question is False
    assert parse_suggestion("NO_QUESTION").no_question is False      # partial until the line ends
    assert parse_suggestion("").has_content is False


def test_parse_no_question_and_bullets():
    assert parse_suggestion("NO_QUESTION", complete=True).no_question
    assert parse_suggestion("NO_QUESTION\n").no_question
    s = parse_suggestion("NO_QUESTION\nANSWER: but here is text", complete=True)
    assert not s.no_question and s.answer == "but here is text"
    s = parse_suggestion("- first point\n* second point\n• third", complete=True)
    assert s.answer == "first point second point third"


# ---- render ----------------------------------------------------------------------------------
READY = {"1": ReadyAnswer("1", "Tell me about yourself", "“I'm Sam.”")}


def test_answer_parts_ready_answer_with_add():
    p = answer_parts(parse_suggestion("READY: 1\nADD: I also mentor.\n", True), READY)
    assert p == [("READY ANSWER · Tell me about yourself\n", "label"), ("“I'm Sam.”\n", "ready"),
                 ("I also mentor.\n", "add")]


def test_answer_parts_generated_docs_and_missing_ready():
    p = answer_parts(parse_suggestion("READY: NONE\nANSWER: I would retry.\nDOCS: veja a doc\n", True), READY)
    assert p[:2] == [("SUGGESTED ANSWER\n", "label"), ("I would retry.\n", "answer")]
    assert p[2][1] == "warn" and "veja a doc" in p[2][0]
    p = answer_parts(parse_suggestion("READY: 9\nANSWER: fallback\n", True), READY)
    assert p == [("(ready answer 9 not found in the profile)\n", "label"), ("fallback\n", "answer")]
    assert answer_parts(parse_suggestion("NO_QUESTION", True), READY) == []
    assert {k for _, k in p} <= set(KINDS)


# ---- prompts ---------------------------------------------------------------------------------
def test_system_prompt_generic_rules(profile: Path, make_settings):
    k = Knowledge.load(profile)
    s = make_settings(profile, ai={"answer_words_target": 55, "answer_words_max": 66})
    p = build_system_prompt(k, s)
    assert "copilot of Sam Lee" in p and "Backend Engineer" in p
    assert "about 55 words, never more than 66" in p
    assert "in Spanish" in p                                                 # native language
    assert "Sam Lee, C#, RabbitMQ" in p                                      # vocabulary
    assert "Use ONE case per answer" in p and "Never mix two cases" in p     # one case
    assert "Honesty" in p and "say so honestly in the first sentence" in p
    assert "Never invent, estimate or round a number" in p
    assert "outrank your general knowledge" in p
    assert "Never deny experience because of a mis-transcribed word" in p
    assert "NO_QUESTION" in p and "Do NOT translate" in p
    for marker in ("READY:", "ANSWER:", "ADD:", "DOCS:", "INTENT:"):
        assert marker in p
    assert "{" not in p.replace("{}", "")                                    # every placeholder filled


def test_other_prompts(profile: Path):
    k = Knowledge.load(profile)
    t = build_translate_system(k)
    assert t.startswith("Translate") and "natural Spanish" in t and "Sam Lee" in t
    assert TRANSLATE_SYSTEM.startswith("Translate")
    assert CHECK_SYSTEM.startswith("You check") and "'yes' or 'no'" in CHECK_SYSTEM
    assert "READY: NONE" in FORCE_NEW_ANSWER
    r = build_research_request("What is the GIL?", ["docs.python.org"])
    assert "restricted to docs.python.org" in r
    assert "<interviewer_said>What is the GIL?</interviewer_said>" in r
    assert "restricted" not in build_research_request("q", [])
    assert fill("{a} {b} {c}", a=1, b="x") == "1 x {c}"
