"""Eval runner: ``python -m interview_copilot eval [options]``.

Every question of ``<profile>/evals/questions.json`` goes, as text, through the same engine the app
uses (``CopilotEngine.answer``, history cleared first, same prompt, context and model). For each one:

- time to first token, to first content on screen and total time are measured;
- the answer is rendered as the window would show it (``render.answer_parts``);
- keyword checks (``must_contain`` / ``must_not_contain``) and automatic checks run
  (more than one real case, word limit, ready-answer check decision);
- a judge model grades it with a 6-criterion rubric (see :mod:`.judge`).

Writes ``logs/evals/results_<round>.json`` and ``logs/evals/report_<round>.md``.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import json
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import judge as judge_mod
from . import report as report_mod

if TYPE_CHECKING:
    from ..ai.engine import CopilotEngine
    from ..knowledge.loader import Knowledge
    from ..settings import Settings

Out = Callable[[str], None]

QUOTES = (("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'), ("–", "-"), ("—", "-"), (" ", " "))
SHOWN_KINDS = ("ready", "answer", "add")
CASE_MAP_HEADING = re.compile(r"(?i)topic\s*(→|->|to)\s*case|case\s+map")
KEYWORDS_LINE = re.compile(r"^\s*[-*]\s*\*\*\s*keywords\s*:?\s*\*\*\s*:?\s*(.+)$", re.I)
PITCH_TITLE = re.compile(r"(?i)\byourself\b|\bintroduc")


# ---- text checks -------------------------------------------------------------------------------
def norm(text: str) -> str:
    """Lower case with typographic quotes, dashes and non-breaking spaces normalized."""
    t = (text or "").lower()
    for a, b in QUOTES:
        t = t.replace(a, b)
    return t


def contains(text_n: str, term: str) -> bool:
    """``term`` in the normalized text; short terms (4 characters or less) match whole words only."""
    t = norm(term).strip()
    if not t:
        return False
    if len(t) <= 4 and re.fullmatch(r"[\w&+#\-.]+", t):
        return re.search(rf"(?<![\w]){re.escape(t)}(?![\w])", text_n) is not None
    return t in text_n


def keyword_check(answer: str, item: dict[str, Any]) -> dict[str, Any]:
    """``missing`` must_contain terms, ``forbidden`` must_not_contain hits and the ``coverage`` (0-1)."""
    tn = norm(answer)
    must = item.get("must_contain") or []
    missing = [d.get("term", "") for d in must
               if not any(contains(tn, a) for a in [d.get("term", "")] + list(d.get("alternatives") or []))]
    forbidden = []
    for n in item.get("must_not_contain") or []:
        hits = [w for w in n.get("words") or [] if contains(tn, w)]
        if hits:
            forbidden.append(f'{n.get("description", "forbidden")} ({", ".join(h.strip() for h in hits)})')
    return {"missing": missing, "forbidden": forbidden,
            "coverage": (len(must) - len(missing)) / len(must) if must else 1.0}


def word_count(text: str) -> int:
    """Spoken words (numbers count as words)."""
    return len(re.findall(r"[A-Za-zÀ-ÿ0-9'’&+#\-]+", text or ""))


@dataclass
class Case:
    """A real case of the projects file and the words that identify it in an answer."""

    name: str
    keywords: list[str] = field(default_factory=list)

    @property
    def terms(self) -> list[str]:
        return [self.name] + self.keywords


def parse_cases(text: str) -> list[Case]:
    """Cases from a projects markdown file: each ``## <Case name>`` (except the topic → case map),
    with the optional ``- **Keywords:** a, b, c`` bullet."""
    cases: list[Case] = []
    current: Case | None = None
    for line in (text or "").splitlines():
        m = re.match(r"^##\s+(.+?)\s*#*\s*$", line)
        if m:
            name = m.group(1).strip()
            current = None if CASE_MAP_HEADING.search(name) else Case(name)
            if current:
                cases.append(current)
            continue
        if line.startswith("# "):
            current = None
            continue
        k = KEYWORDS_LINE.match(line)
        if k and current is not None:
            current.keywords += [w.strip().strip("`*") for w in k.group(1).split(",") if w.strip()]
    return cases


def projects_text(knowledge: Knowledge) -> str:
    """Text of every document of the ``03-projects`` folder."""
    return "\n\n".join(d.text for d in knowledge.documents_of("projects"))


def detect_cases(answer: str, cases: list[Case]) -> list[str]:
    """Names of the cases cited in the answer (by name or keyword)."""
    tn = norm(answer)
    return [c.name for c in cases if any(contains(tn, t) for t in c.terms)]


def is_pitch(item: dict[str, Any], gen: dict[str, Any] | None = None) -> bool:
    """The introduction ("tell me about yourself") may be longer than the other answers."""
    if str(item.get("id")) == "1":
        return True
    category = str(item.get("category", "")).lower()
    if category == "pitch":
        return True
    if category in ("behavioral", "behavioural") and "yourself" in str(item.get("question", "")).lower():
        return True
    return bool(gen and gen.get("type") == "ready answer" and PITCH_TITLE.search(gen.get("ready_answer", "")))


def word_limit(item: dict[str, Any], gen: dict[str, Any], words_max: int, pitch_max: int) -> int:
    """Word limit of one answer."""
    return pitch_max if is_pitch(item, gen) else words_max


def auto_checks(item: dict[str, Any], gen: dict[str, Any], cases: list[Case], words_max: int,
                pitch_max: int) -> dict[str, Any]:
    """Automatic checks: real cases cited and the word limit."""
    cited = detect_cases(gen.get("shown", ""), cases)
    limit = word_limit(item, gen, words_max, pitch_max)
    return {"cases": cited, "more_than_one_case": len(cited) > 1, "word_limit": limit,
            "over_limit": gen.get("words", 0) > limit}


# ---- generation (the app's engine) ------------------------------------------------------------
def generate(engine: CopilotEngine, item: dict[str, Any], timeout: float = 60.0) -> dict[str, Any]:
    """Ask one question exactly like the app (history cleared) and measure it."""
    from ..ai.parsing import parse_suggestion
    from ..render import answer_parts

    engine.history.clear()
    marks: dict[str, float] = {}
    res: dict[str, Any] = {"translation": "", "raw": "", "stop": None, "errors": []}
    done = threading.Event()

    def on_suggestion(text: str) -> None:
        marks.setdefault("ttft", time.perf_counter())
        res["raw"] = text

    def on_suggestion_done(stop: str | None) -> None:
        res["stop"] = stop
        marks.setdefault("end", time.perf_counter())

    t0 = time.perf_counter()
    engine.answer(item["question"],
                  on_translation=lambda t: res.__setitem__("translation", t),
                  on_suggestion=on_suggestion,
                  on_first_content=lambda t: marks.setdefault("first", t),
                  on_suggestion_done=on_suggestion_done,
                  on_done=done.set, on_error=res["errors"].append, suggest=True)
    if not done.wait(timeout):
        res["errors"].append(f"timed out after {timeout:.0f}s")
    s = parse_suggestion(res["raw"], complete=True)
    ready = engine.knowledge.ready_answers
    parts = answer_parts(s, ready, complete=True)
    shown = "".join(t for t, k in parts if k in SHOWN_KINDS).strip()
    ra = ready.get(s.model_id) if s.model_id else None
    turn = engine.history[-1] if engine.history else None
    if ra:
        kind = "ready answer"
    elif s.answer:
        kind = "generated"
    elif s.no_question:
        kind = "not a question"
    else:
        kind = "empty"

    def since(key: str) -> float | None:
        return round(marks[key] - t0, 2) if key in marks else None

    return {
        "type": kind,
        "shown": shown,
        "docs_warning": "".join(t for t, k in parts if k == "warn").strip(),
        "ready_answer_id": s.model_id or "",
        "ready_answer": ra.title if ra else "",
        "add": s.add,
        "intent": s.intent,
        "translation": res["translation"].strip(),
        "raw": res["raw"],
        "stop": res["stop"],
        "errors": res["errors"],
        "ready_check": turn.check if turn is not None else None,
        "words": word_count(shown),
        "ttft_s": since("ttft"),
        "first_content_s": since("first"),
        "total_s": round(marks.get("end", time.perf_counter()) - t0, 2),
    }


# ---- verdict -----------------------------------------------------------------------------------
def verdict(result: dict[str, Any]) -> None:
    """Set ``failed`` and ``reason`` from keyword checks, automatic checks, errors and the judge."""
    gen, kw, checks = result["gen"], result["keywords"], result["checks"]
    j = result.get("judge", {})
    reasons: list[str] = []
    if kw["forbidden"]:
        reasons.append("contains: " + "; ".join(kw["forbidden"]))
    if checks["more_than_one_case"]:
        reasons.append("more than one real case: " + ", ".join(checks["cases"]))
    if j.get("failed"):
        reasons.append(j.get("fail_reason") or "failed by the judge")
    if gen["type"] == "empty" or gen.get("errors"):
        reasons.append("no answer" + (f" ({'; '.join(gen['errors'])})" if gen.get("errors") else ""))
    result["failed"] = bool(reasons)
    summary = j.get("summary") or (f"judge error: {j['error']}" if j.get("error") else "")
    missing = kw["missing"]
    if reasons:
        result["reason"] = "; ".join(reasons)
    elif summary and summary.lower() != "ok":
        result["reason"] = summary
    else:
        result["reason"] = ("missing: " + ", ".join(missing)) if missing else "ok"


# ---- main --------------------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    """Options of the ``eval`` command."""
    p = argparse.ArgumentParser(prog="interview-copilot eval",
                                description="Run the answer-quality evals of the active profile.")
    p.add_argument("--round", default="v1", help="round name: writes results_NAME.json and report_NAME.md "
                   "in logs/evals/ (default: v1)")
    p.add_argument("--compare-with", metavar="FILE",
                   help="results file of a previous round (relative to logs/evals/), e.g. results_v1.json")
    p.add_argument("--ids", help="comma-separated question ids, e.g. 1,2,V1")
    p.add_argument("--no-judge", action="store_true", help="skip the judge model (answers + checks only)")
    p.add_argument("--rejudge", action="store_true",
                   help="reuse the saved answers of this round; only judge and report again")
    p.add_argument("--judge-model", help="judge model (default: [evals] judge_model)")
    p.add_argument("--parallel", type=int, help="parallel judge calls (default: [evals] parallel)")
    return p


def load_questions(profile_path: Path) -> dict[str, Any]:
    """Parse ``<profile>/evals/questions.json``."""
    path = profile_path / "evals" / "questions.json"
    if not path.is_file():
        raise FileNotFoundError(f"Eval questions not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    data.setdefault("questions", [])
    return data


def _anthropic_client(settings: Settings) -> Any:
    import anthropic

    return anthropic.Anthropic(api_key=settings.anthropic_key, max_retries=1, timeout=120)


def main(argv: list[str] | None, settings: Settings, out: Out = print, *,
         judge_retry_pause_s: float = 2.0) -> int:
    """Entry point of ``python -m interview_copilot eval``. Returns the exit code."""
    from ..knowledge.loader import Knowledge

    args = build_parser().parse_args(list(argv or []))
    round_name = re.sub(r"[^\w.\-]", "_", args.round.strip()) or "v1"
    evals_cfg = settings.evals
    judge_model = args.judge_model or str(evals_cfg.get("judge_model", "claude-sonnet-5-5"))
    parallel = max(1, args.parallel or int(evals_cfg.get("parallel", 4)))
    words_max = int(settings.ai.get("answer_words_max", 80))
    pitch_max = int(evals_cfg.get("pitch_words_max", 100))

    knowledge = Knowledge.load(settings.profile_path)
    try:
        questions = load_questions(knowledge.profile.path)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        out(f"[error] {e}")
        return 1
    all_items = questions["questions"]
    items = all_items
    if args.ids:
        wanted = {x.strip() for x in args.ids.split(",") if x.strip()}
        items = [i for i in all_items if str(i["id"]) in wanted]
        unknown = wanted - {str(i["id"]) for i in items}
        if unknown:
            out(f"[warning] unknown question ids: {', '.join(sorted(unknown))}")
    if not items:
        out("[error] no questions to run")
        return 1
    by_id = {str(i["id"]): i for i in all_items}

    folder = settings.logs_dir / "evals"
    folder.mkdir(parents=True, exist_ok=True)
    results_path = folder / f"results_{round_name}.json"
    report_path = folder / f"report_{round_name}.md"
    log_path = folder / f"answer_selection_{round_name}.jsonl"
    needs_key = not args.rejudge or not args.no_judge
    if needs_key and not settings.anthropic_key:
        out("[error] ANTHROPIC_API_KEY is not set (environment variable or .env file).")
        return 1

    saved: dict[str, Any] = {}
    if results_path.is_file():
        saved = json.loads(results_path.read_text(encoding="utf-8")).get("results", {})
    res: dict[str, dict[str, Any]] = dict(saved) if args.rejudge else {}

    def save() -> None:
        payload = {"round": round_name, "created": dt.datetime.now().isoformat(timespec="seconds"),
                   "profile": knowledge.profile.name, "model": settings.ai.get("model"),
                   "judge_model": None if args.no_judge else judge_model, "results": res}
        results_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---- 1) answers, through the app's engine
    if args.rejudge:
        missing = [str(i["id"]) for i in items if str(i["id"]) not in res]
        if missing:
            out(f"[error] --rejudge: no saved answers in {results_path.name} for ids {', '.join(missing)}")
            return 1
    else:
        from ..console import build_engine

        engine = build_engine(settings, knowledge, out)
        engine.log_path = log_path
        engine.warm_cache()
        out(f"\nGenerating {len(items)} answers with {settings.ai.get('model')}...\n")
        for n, item in enumerate(items, 1):
            gen = generate(engine, item)
            res[str(item["id"])] = {"question": item["question"], "category": item.get("category", ""),
                                    "gen": gen}
            out(f"[{n:>2}/{len(items)}] {str(item['id']):>3} · {gen['type']:<14} · first content "
                f"{report_mod.fmt(gen['first_content_s'], 's'):>6} · total {gen['total_s']:>5}s · "
                f"{gen['words']} words")
            if n == 1 and gen["errors"] and not gen["raw"]:
                out(f"[error] the first question failed, stopping: {'; '.join(gen['errors'])}")
                save()
                return 1
        save()
        s = engine.stats
        out(f"\nCache: {s.cache_read} tokens read, {s.cache_write} written, {s.calls} calls.")

    # ---- 2) checks (always recomputed: cheap and deterministic)
    cases = parse_cases(projects_text(knowledge))
    for item in items:
        r = res[str(item["id"])]
        r["keywords"] = keyword_check(r["gen"]["shown"], item)
        r["checks"] = auto_checks(item, r["gen"], cases, words_max, pitch_max)
        r["gen"]["word_limit"] = r["checks"]["word_limit"]

    # ---- 3) judge
    suggestions = ""
    grade: judge_mod.Judge | None = None
    client: Any = None
    if not args.no_judge:
        client = _anthropic_client(settings)
        system = judge_mod.build_judge_system(knowledge, questions, projects_text(knowledge), settings.ai,
                                              pitch_max)
        grade = judge_mod.Judge(client, judge_model, system, retry_pause_s=judge_retry_pause_s)
        out(f"\nJudging with {judge_model} ({parallel} in parallel)...")
        with cf.ThreadPoolExecutor(max_workers=parallel) as ex:
            futures = {}
            for item in items:
                eq = item.get("equivalent_to")
                original = by_id.get(str(eq)) if eq not in (None, "") else None
                futures[ex.submit(grade, item, res[str(item["id"])]["gen"], original)] = item
            for f in cf.as_completed(futures):
                item = futures[f]
                j = f.result()
                res[str(item["id"])]["judge"] = j
                score = f"{report_mod.fmt(j.get('total'))}/{judge_mod.MAX_TOTAL}"
                out(f"  {str(item['id']):>3} · score {score} · "
                    f"{report_mod.one_line(j.get('summary') or j.get('error', ''), 90)}")
        if grade.fatal:
            out(f"[error] judge: {grade.fatal}")
    else:
        for item in items:
            res[str(item["id"])].pop("judge", None)

    # ---- 4) verdicts
    for item in items:
        verdict(res[str(item["id"])])

    # ---- 5) suggestions (judge model, never applied)
    if grade is not None and not grade.fatal:
        data = []
        for i in items:
            r = res[str(i["id"])]
            data.append({"id": i["id"], "question": i["question"], "type": r["gen"]["type"],
                         "words": r["gen"]["words"], "score": r.get("judge", {}).get("total"),
                         "failed": r["failed"], "reason": r["reason"],
                         "problems": r.get("judge", {}).get("problems", []),
                         "missing": r["keywords"]["missing"], "answer": r["gen"]["shown"][:900]})
        suggestions = judge_mod.suggestions(client, judge_model, knowledge, data)
    save()

    # ---- 6) report
    previous, previous_name = None, ""
    if args.compare_with:
        prev_path = Path(args.compare_with)
        if not prev_path.is_absolute():
            prev_path = folder / prev_path
        if not prev_path.is_file():
            out(f"[warning] --compare-with: {prev_path} not found, no comparison")
        elif prev_path.resolve() == results_path.resolve():
            out("[warning] --compare-with points to this round's own results, no comparison")
        else:
            previous = json.loads(prev_path.read_text(encoding="utf-8")).get("results", {})
            previous_name = prev_path.name
    notes_path = knowledge.profile.path / "evals" / "notes.md"
    notes = notes_path.read_text(encoding="utf-8-sig") if notes_path.is_file() else ""
    meta = {"round": round_name, "created": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "profile": knowledge.profile.name, "model": settings.ai.get("model"),
            "judge_model": None if args.no_judge else judge_model, "words_max": words_max,
            "pitch_max": pitch_max, "results_file": f"logs/evals/{results_path.name}",
            "log_file": f"logs/evals/{log_path.name}"}
    report_path.write_text(report_mod.build_report(meta, items, res, suggestions=suggestions, notes=notes,
                                                   previous=previous, previous_name=previous_name),
                           encoding="utf-8")
    n_ok = sum(1 for i in items if not res[str(i["id"])].get("failed", True))
    out(f"\nPassed {n_ok} of {len(items)}. Report: {report_path}")
    return 0
