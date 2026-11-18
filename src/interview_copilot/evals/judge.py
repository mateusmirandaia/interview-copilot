"""LLM judge for the evals: rubric, automatic-fail rules, API error descriptions and suggestions."""

from __future__ import annotations

import json
import re
import threading
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..knowledge.loader import Knowledge

#: (key, label) of the six rubric criteria, each scored 0-2
CRITERIA: list[tuple[str, str]] = [
    ("correctness", "Correctness"),
    ("real_cases", "Real cases"),
    ("simplicity", "Simplicity"),
    ("focus", "Focus"),
    ("speakable", "Speakable"),
    ("answers_question", "Answers the question"),
]
MAX_TOTAL = 2 * len(CRITERIA)

#: fixed problem tags the judge may return
TAGS: dict[str, str] = {
    "too_long": "answer too long (over the word limit)",
    "too_short": "answer too short",
    "missing_real_case": "the expected real case is missing",
    "invented_case": "invented case, number, detail or link between cases",
    "wrong_case": "wrong real case for the question",
    "more_than_one_case": "mixes more than one real case in the same answer",
    "not_simplest_first": "does not start with the simplest solution",
    "technical_error": "technical error",
    "invented_number": "number not found in the profile or the official docs",
    "does_not_answer": "does not answer what was asked",
    "bullets_or_extra": "bullets, labels, cuts or an extra part",
    "hard_to_say": "English that is hard to say out loud",
    "unsuitable_ready_answer": "the chosen ready answer does not match the question",
    "denies_real_experience": "denies or hides experience that is in the profile",
    "breaks_instructions": "breaks a rule from the profile instructions",
}

GENERIC_AUTO_FAIL = [
    "contains any item of the question's must_not_contain list;",
    "cites a number that is written neither in <context_files> nor in the official documentation;",
    "mixes two or more real cases in the same answer (unless the interviewer asked for more examples);",
    "invents experience, an employer, a client, a project or a result that is not in the profile files;",
    "denies or hides experience that IS in the profile files;",
    "contradicts a VERIFIED FACT below.",
]

JUDGE_SYSTEM = """You are a strict evaluator of a real-time interview copilot. The copilot shows {name} (applying for {target_role}) a complete answer that the candidate will SAY out loud in the interview. You grade that answer.

Grade each criterion from 0 to 2 (0 = bad, 1 = partial, 2 = good):
- correctness: aligned with the VERIFIED FACTS, the profile files and the official documentation; no wrong technical claims.
- real_cases: uses only cases from the projects file (below), told exactly the way they are written there, and the case the "Topic -> case" map assigns to the topic. No invented project, detail, number or link between cases. If the question asks for an example or a project and the answer gives none or the wrong one, score low. If no case is needed and none is cited, score 2.
- simplicity: starts with the simplest solution before the more complex one. If not applicable (pitch, behavioral), score 2.
- focus: stays on what the role and the profile instructions emphasize; one main idea, no tangents. If not applicable, score 2.
- speakable: one complete spoken answer, no cuts, no bullets, no labels, no "Extra" part, natural English, about {words_target} words and never more than {words_max} (the introduction pitch may have up to {pitch_max}). One main idea, at most one real case, no closing summary. Penalize answers over the limit.
- answers_question: goes straight to what was asked.

NUMBERS: check every number in the answer (limits, durations, counts, versions, percentages). A number is acceptable ONLY if it is written in <context_files> (the candidate's profile files) or in the official documentation (the <official_docs> section inside <context_files>). If you find it, accept it and report the file it came from. A number found in neither is an invented number.

AUTOMATIC FAIL ("failed": true) if the answer:
{auto_fail}

VERIFIED FACTS (must not be contradicted):
{facts}

<projects_file>
{projects}
</projects_file>

The full material the copilot had (profile files and official documentation), to verify facts and numbers:
<context_files>
{context}
</context_files>

Allowed problem tags (use only these keys): {tags}

Reply with ONLY a JSON object, no markdown fence:
{{"scores": {{"correctness": 0-2, "real_cases": 0-2, "simplicity": 0-2, "focus": 0-2, "speakable": 0-2, "answers_question": 0-2}},
 "failed": true|false,
 "fail_reason": "short reason, empty if not failed",
 "summary": "one line: the main issue, or 'ok'",
 "problems": ["tag", ...],
 "numbers": [{{"number": "30 seconds", "source": "file name where it is written, or 'not found'"}}],
 "understood_question": true|false}}"""

SUGGEST_SYSTEM = (
    "You review the results of an automated evaluation of an interview copilot (for {name}, applying for "
    "{target_role}). Based ONLY on the data given, write a short list (5 to 10 items) of concrete "
    "SUGGESTIONS to adjust the copilot's system prompt or the candidate's profile files. Each item: what "
    "to change, why (cite question ids) and the expected effect. Do not claim anything was applied. "
    "Markdown list only."
)

NON_RETRYABLE = {400, 401, 403, 404, 413, 422}


def _bullets(lines: list[str]) -> str:
    return "\n".join(f"- {x}" for x in lines) if lines else "- (none)"


def build_judge_system(knowledge: Knowledge, questions: dict[str, Any], projects_text: str,
                       ai: dict[str, Any], pitch_max: int) -> list[dict[str, Any]]:
    """System blocks for the judge (one cached text block)."""
    p = knowledge.profile
    values = {
        "name": p.name,
        "target_role": p.target_role,
        "words_target": int(ai.get("answer_words_target", 70)),
        "words_max": int(ai.get("answer_words_max", 80)),
        "pitch_max": pitch_max,
        "auto_fail": _bullets(GENERIC_AUTO_FAIL + [str(x) for x in questions.get("auto_fail", [])]),
        "facts": _bullets([str(x) for x in questions.get("facts", [])]),
        "projects": projects_text.strip() or "(no projects file)",
        "context": knowledge.context_block(),
        "tags": ", ".join(TAGS),
    }
    text = JUDGE_SYSTEM.replace("{{", "{").replace("}}", "}")
    # free-form blocks last, so braces inside them are never treated as placeholders
    for key in ("name", "target_role", "words_target", "words_max", "pitch_max", "tags", "auto_fail",
                "facts", "projects", "context"):
        text = text.replace("{" + key + "}", str(values[key]))
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


def describe_api_error(e: BaseException) -> str:
    """Readable one-line description of an Anthropic API error, with a hint when the cause is known."""
    status = getattr(e, "status_code", None)
    body = getattr(e, "body", None)
    err = body.get("error", body) if isinstance(body, dict) else {}
    etype = err.get("type", "") if isinstance(err, dict) else ""
    message = (err.get("message") if isinstance(err, dict) else None) or getattr(e, "message", None) or str(e)
    if status is None:
        if type(e).__name__ in ("APIConnectionError", "APITimeoutError"):
            return f"cannot reach the Anthropic API ({type(e).__name__}: {message})"
        return f"{type(e).__name__}: {message}"
    hint = ""
    low = str(message).lower()
    if "credit balance" in low:
        hint = "check your credit balance"
    elif status == 401:
        hint = "check ANTHROPIC_API_KEY"
    elif status == 404 or "model" in low and "not found" in low:
        hint = "check the model name"
    elif status == 429:
        hint = "rate limited, try a lower --parallel"
    elif status in (500, 529):
        hint = "the API is overloaded, try again later"
    head = f"{status} {etype}".strip()
    return f"{head} — {hint}: {message}" if hint else f"{head} — {message}"


def is_retryable(e: BaseException) -> bool:
    """False for client errors that would fail again (bad request, auth, credit balance...)."""
    return getattr(e, "status_code", None) not in NON_RETRYABLE


def parse_json(text: str) -> dict[str, Any]:
    """First JSON object found in ``text``."""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise ValueError(f"the judge did not return JSON: {(text or '')[:200]}")
    return json.loads(m.group(0))


def normalize_verdict(j: dict[str, Any]) -> dict[str, Any]:
    """Clamp scores to 0-2, keep only known tags and well-formed number entries."""
    raw_scores = j.get("scores") or {}
    scores = {k: max(0, min(2, int(raw_scores.get(k, 0) or 0))) for k, _ in CRITERIA}
    return {
        "scores": scores,
        "total": sum(scores.values()),
        "failed": bool(j.get("failed")),
        "fail_reason": str(j.get("fail_reason") or ""),
        "summary": str(j.get("summary") or ""),
        "problems": [p for p in j.get("problems") or [] if p in TAGS],
        "numbers": [{"number": str(n.get("number", "")), "source": str(n.get("source", ""))}
                    for n in j.get("numbers") or [] if isinstance(n, dict)],
        "understood_question": bool(j.get("understood_question", True)),
    }


def build_payload(item: dict[str, Any], gen: dict[str, Any], original: dict[str, Any] | None) -> dict[str, Any]:
    """User message for one judged answer."""
    payload: dict[str, Any] = {
        "id": item["id"],
        "category": item.get("category", ""),
        "question": item["question"],
        "equivalent_to_question": original["question"] if original else None,
        "must_contain": [d.get("term", "") for d in item.get("must_contain", [])],
        "must_not_contain": [n.get("description", "") + (f" ({', '.join(n['words'])})" if n.get("words") else "")
                             for n in item.get("must_not_contain", [])],
        "copilot_answer_shown": gen.get("shown") or "(empty)",
        "answer_type": gen.get("type"),
        "ready_answer_title": gen.get("ready_answer", ""),
        "add_sentence": gen.get("add", ""),
        "docs_warning": gen.get("docs_warning", ""),
        "word_count": gen.get("words"),
        "word_limit": gen.get("word_limit"),
        "copilot_intent": gen.get("intent", ""),
        "copilot_translation": gen.get("translation", ""),
    }
    if original:
        payload["note"] = ("This question has speech-recognition errors on purpose. 'understood_question' = "
                           "did the copilot understand it as the original question?")
    return payload


class Judge:
    """Calls the judge model. Retries twice; a non-retryable API error stops every later call."""

    def __init__(self, client: Any, model: str, system: list[dict[str, Any]], retries: int = 2,
                 retry_pause_s: float = 2.0, max_tokens: int = 1500):
        self.client = client
        self.model = model
        self.system = system
        self.retries = retries
        self.retry_pause_s = retry_pause_s
        self.max_tokens = max_tokens
        self.fatal: str | None = None
        self._lock = threading.Lock()

    def __call__(self, item: dict[str, Any], gen: dict[str, Any],
                 original: dict[str, Any] | None = None) -> dict[str, Any]:
        """Judge one answer. Returns the normalized verdict or ``{"error": "..."}``."""
        if self.fatal:
            return {"error": self.fatal}
        content = json.dumps(build_payload(item, gen, original), ensure_ascii=False, indent=1)
        last = ""
        for attempt in range(self.retries + 1):
            try:
                msg = self.client.messages.create(
                    model=self.model, max_tokens=self.max_tokens, system=self.system,
                    messages=[{"role": "user", "content": content}])
                text = "".join(getattr(b, "text", "") for b in msg.content)
                return normalize_verdict(parse_json(text))
            except Exception as e:  # noqa: BLE001 - reported in the results
                last = describe_api_error(e)
                if not is_retryable(e):
                    with self._lock:
                        self.fatal = self.fatal or last
                    break
            if attempt < self.retries and self.retry_pause_s:
                time.sleep(self.retry_pause_s)
        return {"error": last}


def suggestions(client: Any, model: str, knowledge: Knowledge, data: list[dict[str, Any]]) -> str:
    """Ask the judge model for prompt/profile suggestions (never applied automatically)."""
    p = knowledge.profile
    system = SUGGEST_SYSTEM.replace("{name}", p.name).replace("{target_role}", p.target_role)
    try:
        msg = client.messages.create(model=model, max_tokens=2500, system=system,
                                     messages=[{"role": "user", "content": json.dumps(data, ensure_ascii=False)}])
        return "".join(getattr(b, "text", "") for b in msg.content).strip()
    except Exception as e:  # noqa: BLE001 - shown in the report
        return f"(could not generate suggestions: {describe_api_error(e)})"
