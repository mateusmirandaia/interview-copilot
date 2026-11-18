"""Markdown report of an eval round (``logs/evals/report_<round>.md``)."""

from __future__ import annotations

import re
import statistics
from collections.abc import Iterable
from typing import Any

from .judge import CRITERIA, MAX_TOTAL, TAGS

TYPES = ("ready answer", "generated", "not a question", "empty")
SHORT_WORDS = 40

Item = dict[str, Any]
Result = dict[str, Any]


def mean(values: Iterable[float | None]) -> float | None:
    """Average of the non-None values, rounded to 2 decimals (None when empty)."""
    v = [x for x in values if x is not None]
    return round(float(statistics.mean(v)), 2) if v else None


def fmt(x: Any, suffix: str = "") -> str:
    """``–`` for None, otherwise the value with a suffix."""
    return "–" if x is None else f"{x}{suffix}"


def one_line(text: str, n: int = 110) -> str:
    """Single line, table-safe, truncated to ``n`` characters."""
    t = re.sub(r"\s+", " ", str(text or "")).replace("|", "/").strip()
    return t if len(t) <= n else t[: n - 1] + "…"


def _judged(rows: list[tuple[Item, Result]]) -> list[tuple[Item, Result]]:
    return [(i, r) for i, r in rows if "scores" in r.get("judge", {})]


def _over(r: Result) -> bool:
    return bool(r.get("checks", {}).get("over_limit"))


def _limit(r: Result) -> int | None:
    return r.get("checks", {}).get("word_limit")


# ---- comparison ----------------------------------------------------------------------------------
def comparison_section(items: list[Item], res: dict[str, Result], prev: dict[str, Result],
                       round_name: str, prev_name: str) -> list[str]:
    """Previous round vs this round: pass count, averages, latency, improved/worsened lists."""
    keys = [str(i["id"]) for i in items if str(i["id"]) in res]

    def passed(d: dict[str, Result]) -> int:
        return sum(1 for k in keys if k in d and not d[k].get("failed", True))

    def crit(d: dict[str, Result], c: str) -> float | None:
        return mean(d[k]["judge"]["scores"].get(c) for k in keys
                    if k in d and "scores" in d[k].get("judge", {}))

    def total(d: dict[str, Result]) -> float | None:
        return mean(d[k]["judge"].get("total") for k in keys if k in d and "total" in d[k].get("judge", {}))

    def latency(d: dict[str, Result]) -> float | None:
        return mean(d[k].get("gen", {}).get("first_content_s") for k in keys if k in d)

    in_both = sum(1 for k in keys if k in prev)
    L = [f"## Comparison with the previous round (`{prev_name}`)", "",
         f"Questions in both rounds: {in_both} of {len(keys)}.", "",
         f"| | Previous | {round_name} |", "| --- | --- | --- |",
         f"| Passed | {passed(prev)} of {in_both} | {passed(res)} of {len(keys)} |",
         f"| Average total (of {MAX_TOTAL}) | {fmt(total(prev))} | {fmt(total(res))} |"]
    for c, label in CRITERIA:
        L.append(f"| {label} | {fmt(crit(prev, c))} | {fmt(crit(res, c))} |")
    L.append(f"| Average latency (first content) | {fmt(latency(prev), ' s')} | {fmt(latency(res), ' s')} |")

    by_id = {str(i["id"]): i for i in items}
    worse: list[tuple[Item, Result, Result]] = []
    better: list[tuple[Item, Result, Result]] = []
    for k in keys:
        if k not in prev:
            continue
        a, b = prev[k], res[k]
        ta, tb = a.get("judge", {}).get("total"), b.get("judge", {}).get("total")
        dropped = ta is not None and tb is not None and tb < ta
        rose = ta is not None and tb is not None and tb > ta
        if dropped or (b.get("failed") and not a.get("failed")):
            worse.append((by_id[k], a, b))
        elif rose or (a.get("failed") and not b.get("failed")):
            better.append((by_id[k], a, b))

    def table(rows: list[tuple[Item, Result, Result]]) -> list[str]:
        out = ["| id | question | score before → now | failed before → now | why (now) | before |",
               "| --- | --- | --- | --- | --- | --- |"]
        for i, a, b in rows:
            out.append(f"| {i['id']} | {one_line(i['question'], 60)} | "
                       f"{fmt(a.get('judge', {}).get('total'))} → {fmt(b.get('judge', {}).get('total'))} | "
                       f"{'yes' if a.get('failed') else 'no'} → {'yes' if b.get('failed') else 'no'} | "
                       f"{one_line(b.get('reason', ''), 120)} | {one_line(a.get('reason', ''), 80)} |")
        return out

    L += ["", f"**Improved:** {len(better)}" + ("" if better else " (none)"), ""]
    if better:
        L += table(better) + [""]
    L += [f"**Worsened:** {len(worse)}" + ("" if worse else " (none)"), ""]
    if worse:
        L += table(worse) + ["", "_Regressions are only listed, nothing is changed automatically._"]
    return L + [""]


# ---- automatic checks ----------------------------------------------------------------------------
def checks_section(rows: list[tuple[Item, Result]], log_name: str) -> list[str]:
    """Round checks that should all be zero, plus the ready-answer check decisions."""
    multi = [(i, r) for i, r in rows if r.get("checks", {}).get("more_than_one_case")]
    over = [(i, r) for i, r in rows if _over(r)]
    unsuitable = [(i, r) for i, r in rows if r["gen"].get("type") == "ready answer"
                  and "unsuitable_ready_answer" in r.get("judge", {}).get("problems", [])]
    forbidden = [(i, r) for i, r in rows if r.get("keywords", {}).get("forbidden")]
    checks = [(i, r, r["gen"].get("ready_check")) for i, r in rows if r["gen"].get("ready_check")]
    used = [x for x in checks if x[2].get("same_subject") is True]
    rejected = [x for x in checks if x[2].get("same_subject") is False]

    def ids(lst: list[tuple[Item, Result]], extra=lambda r: "") -> str:
        return ", ".join(f"{i['id']}{extra(r)}" for i, r in lst) or "–"

    L = ["## Automatic checks (should all be zero)", "",
         "| Check | Count | Questions |", "| --- | --- | --- |",
         f"| Answers with more than one real case | {len(multi)} | "
         f"{ids(multi, lambda r: ' (' + ', '.join(r['checks']['cases']) + ')')} |",
         f"| Answers over the word limit | {len(over)} | "
         f"{ids(over, lambda r: ' (' + str(r['gen'].get('words')) + ' words)')} |",
         f"| Forbidden words found (must_not_contain) | {len(forbidden)} | {ids(forbidden)} |",
         f"| Ready answers that do not match the question (judge) | {len(unsuitable)} | "
         f"{ids(unsuitable, lambda r: ' (' + one_line(r['gen'].get('ready_answer', ''), 40) + ')')} |",
         "",
         f"**Ready-answer \"same subject?\" check** (log: `{log_name}`): {len(used)} used, "
         f"{len(rejected)} rejected and replaced by a generated answer."]
    if rejected:
        L += ["", "| id | question | rejected ready answer |", "| --- | --- | --- |"]
        for i, _r, c in rejected:
            L.append(f"| {i['id']} | {one_line(i['question'], 70)} | {one_line(c.get('title', ''), 70)} |")
    return L + [""]


def length_section(rows: list[tuple[Item, Result]], words_max: int, pitch_max: int) -> list[str]:
    """Average/max words and every answer over its limit."""
    words = [r["gen"].get("words", 0) for _, r in rows if r["gen"].get("type") != "not a question"]
    over = sorted([(i, r) for i, r in rows if _over(r)], key=lambda x: -x[1]["gen"].get("words", 0))
    L = [f"## Answer length (limit: {words_max} words; introduction pitch: {pitch_max})", "",
         f"Average {fmt(mean(words))} words · max {max(words, default=0)} · "
         f"**over the limit: {len(over)}**", ""]
    if over:
        L += ["| id | question | type | words | limit |", "| --- | --- | --- | --- | --- |"]
        for i, r in over:
            g = r["gen"]
            ra = f" · {one_line(g['ready_answer'], 40)}" if g.get("ready_answer") else ""
            L.append(f"| {i['id']} | {one_line(i['question'], 70)} | {g.get('type')}{ra} | "
                     f"{g.get('words')} | {_limit(r)} |")
        L.append("")
    return L


# ---- numbered sections ---------------------------------------------------------------------------
def summary_section(rows: list[tuple[Item, Result]]) -> list[str]:
    """1. Summary: pass rate, averages per criterion and category, latency, answer types."""
    judged = _judged(rows)
    passed = [r for _, r in rows if not r.get("failed")]
    first = [r["gen"].get("first_content_s") for _, r in rows]
    ttft = [r["gen"].get("ttft_s") for _, r in rows]
    total = [r["gen"].get("total_s") for _, r in rows]
    errors = [(i, r) for i, r in rows if "error" in r.get("judge", {})]
    L = ["## 1. Summary", "",
         f"- **Passed:** {len(passed)} of {len(rows)} · **Failed:** {len(rows) - len(passed)}",
         f"- **Average total score:** {fmt(mean(r['judge']['total'] for _, r in judged))} of {MAX_TOTAL}"
         + (f" ({len(judged)} judged)" if len(judged) != len(rows) else ""),
         f"- **Average keyword coverage:** "
         f"{fmt(mean(round(r['keywords']['coverage'] * 100) for _, r in rows), '%')}",
         f"- **Latency (first content on screen):** average {fmt(mean(first), ' s')} · "
         f"max {fmt(max([x for x in first if x is not None], default=None), ' s')}",
         f"- **Latency (first token):** average {fmt(mean(ttft), ' s')} · **complete answer:** average "
         f"{fmt(mean(total), ' s')} · "
         f"max {fmt(max([x for x in total if x is not None], default=None), ' s')}",
         "- **Answer types:** " + ", ".join(
             f"{t}: {sum(1 for _, r in rows if r['gen'].get('type') == t)}" for t in TYPES)]
    if errors:
        L.append(f"- **Judge errors:** {len(errors)} ({one_line(errors[0][1]['judge']['error'], 160)})")
    L += ["", "**Average score per criterion (0 to 2):**", "", "| Criterion | Average |", "| --- | --- |"]
    for c, label in CRITERIA:
        L.append(f"| {label} | {fmt(mean(r['judge']['scores'].get(c) for _, r in judged))} |")
    L += ["", "**Per category:**", "",
          "| Category | Questions | Passed | Average score | Average latency (first content) |",
          "| --- | --- | --- | --- | --- |"]
    categories: list[str] = []
    for i, _ in rows:
        if i.get("category", "") not in categories:
            categories.append(i.get("category", ""))
    for c in categories:
        cr = [(i, r) for i, r in rows if i.get("category", "") == c]
        L.append(f"| {c or '–'} | {len(cr)} | {sum(1 for _, r in cr if not r.get('failed'))} | "
                 f"{fmt(mean(r['judge']['total'] for _, r in _judged(cr)))} | "
                 f"{fmt(mean(r['gen'].get('first_content_s') for _, r in cr), ' s')} |")
    return L + [""]


def all_questions_section(rows: list[tuple[Item, Result]]) -> list[str]:
    """2. One row per question."""
    L = ["## 2. All questions", "",
         "| id | category | score | failed | type | words | reason | first content | total |",
         "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for i, r in rows:
        g = r["gen"]
        L.append(f"| {i['id']} | {one_line(i.get('category', ''), 30)} | "
                 f"{fmt(r.get('judge', {}).get('total'))} | "
                 f"{'yes' if r.get('failed') else 'no'} | {g.get('type')} | "
                 f"{g.get('words')}{' ⚠' if _over(r) else ''} | {one_line(r.get('reason', ''))} | "
                 f"{fmt(g.get('first_content_s'), ' s')} | {fmt(g.get('total_s'), ' s')} |")
    return L + [""]


def worst_section(rows: list[tuple[Item, Result]], n: int = 10) -> list[str]:
    """3. The worst answers (failed first, then lowest score, then keyword coverage), in full."""
    def badness(x: tuple[Item, Result]) -> tuple:
        _, r = x
        return (0 if r.get("failed") else 1, r.get("judge", {}).get("total", 99), r["keywords"]["coverage"])

    L = [f"## 3. Worst {n}", ""]
    for i, r in sorted(rows, key=badness)[:n]:
        g = r["gen"]
        kw = r["keywords"]
        ra = f" ({g['ready_answer']})" if g.get("ready_answer") else ""
        L += [f"### {i['id']} · {i['question']}", "",
              f"- **Score:** {fmt(r.get('judge', {}).get('total'))}/{MAX_TOTAL} · "
              f"**Failed:** {'yes' if r.get('failed') else 'no'} · **Type:** {g.get('type')}{ra} · "
              f"**Words:** {g.get('words')}",
              f"- **What is wrong:** {r.get('reason', '')}"]
        if kw.get("missing"):
            L.append(f"- **Missing:** {', '.join(kw['missing'])}")
        if kw.get("forbidden"):
            L.append(f"- **Forbidden found:** {'; '.join(kw['forbidden'])}")
        L += ["", "> " + (g.get("shown") or "(empty)").replace("\n", "\n> "), ""]
    return L


def problems_section(rows: list[tuple[Item, Result]]) -> list[str]:
    """4. Judge tags and automatic counts that repeat across answers."""
    L = ["## 4. Recurring problems", ""]
    tags: dict[str, list[str]] = {}
    for i, r in _judged(rows):
        for p in r["judge"].get("problems", []):
            tags.setdefault(p, []).append(str(i["id"]))
    for k, ids in sorted(tags.items(), key=lambda kv: -len(kv[1])):
        L.append(f"- **{TAGS.get(k, k)}:** {len(ids)} question(s) ({', '.join(ids)})")
    over = [str(i["id"]) for i, r in rows if _over(r)]
    short = [str(i["id"]) for i, r in rows
             if r["gen"].get("type") not in ("not a question", "empty")
             and r["gen"].get("words", 0) < SHORT_WORDS]
    L.append(f"- **Over the word limit (automatic count):** {len(over)} ({', '.join(over) or '–'})")
    L.append(f"- **Under {SHORT_WORDS} words (automatic count):** {len(short)} ({', '.join(short) or '–'})")
    missing: dict[str, list[str]] = {}
    for i, r in rows:
        for m in r["keywords"].get("missing", []):
            missing.setdefault(m, []).append(str(i["id"]))
    top = sorted(missing.items(), key=lambda kv: -len(kv[1]))[:8]
    if top:
        L.append("- **Most missed keywords:** " + "; ".join(f"{k} ({', '.join(v)})" for k, v in top))
    return L + [""]


def suggestions_section(suggestions: str, notes: str) -> list[str]:
    """5. Suggestions from the judge model and the profile's evals/notes.md (never applied)."""
    L = ["## 5. Suggestions for the prompt or the profile (not applied)", ""]
    if notes.strip():
        L += ["**Notes (`evals/notes.md`):**", "", notes.strip(), ""]
    L += ["**Suggestions from the results:**", "", suggestions.strip() or "(no suggestions generated)", ""]
    return L


def variants_section(rows: list[tuple[Item, Result]], res: dict[str, Result]) -> list[str]:
    """6. Mis-transcribed questions compared with their originals."""
    L = ["## 6. Transcription variants", "",
         "| id | transcribed question | equivalent to | understood? | score | original's score | failed |",
         "| --- | --- | --- | --- | --- | --- | --- |"]
    n = 0
    for i, r in rows:
        if i.get("equivalent_to") in (None, ""):
            continue
        n += 1
        orig = res.get(str(i["equivalent_to"]), {})
        j = r.get("judge", {})
        understood = "–" if "scores" not in j else ("yes" if j.get("understood_question") else "no")
        L.append(f"| {i['id']} | {one_line(i['question'], 80)} | {i['equivalent_to']} | {understood} | "
                 f"{fmt(j.get('total'))} | {fmt(orig.get('judge', {}).get('total'))} | "
                 f"{'yes' if r.get('failed') else 'no'} |")
    if not n:
        L.append("| – | (no variants in this run) | | | | | |")
    return L + [""]


def numbers_section(rows: list[tuple[Item, Result]]) -> list[str]:
    """7. Every number the judge found in the answers and where it is written."""
    nums = [(i, n) for i, r in _judged(rows) for n in r["judge"].get("numbers", [])]
    L = ["## 7. Numbers cited and their source", ""]
    if not nums:
        return L + ["(no numbers reported by the judge)", ""]
    L += ["| id | number | source |", "| --- | --- | --- |"]
    for i, n in nums:
        L.append(f"| {i['id']} | {one_line(n.get('number', ''), 40)} | {one_line(n.get('source', ''), 90)} |")
    return L + [""]


def build_report(meta: dict[str, Any], items: list[Item], res: dict[str, Result], *,
                 suggestions: str = "", notes: str = "", previous: dict[str, Result] | None = None,
                 previous_name: str = "") -> str:
    """Full markdown report. ``meta``: round, created, model, judge_model, profile, words_max,
    pitch_max, results_file, log_file."""
    rows = [(i, res[str(i["id"])]) for i in items if str(i["id"]) in res]
    round_name = str(meta.get("round", ""))
    L = [f"# Eval report · round {round_name}", "",
         f"Generated {meta.get('created', '')} · profile: {meta.get('profile', '')} · app model: "
         f"`{meta.get('model', '')}` · judge: `{meta.get('judge_model') or 'none (--no-judge)'}` · "
         f"{len(rows)} questions", ""]
    if previous is not None:
        L += comparison_section(items, res, previous, round_name, previous_name)
    L += checks_section(rows, str(meta.get("log_file", "")))
    L += length_section(rows, int(meta.get("words_max", 80)), int(meta.get("pitch_max", 100)))
    L += summary_section(rows)
    L += all_questions_section(rows)
    L += worst_section(rows)
    L += problems_section(rows)
    L += suggestions_section(suggestions, notes)
    L += variants_section(rows, res)
    L += numbers_section(rows)
    L += ["---", "",
          f"Full answers, translations, intents and per-criterion scores: `{meta.get('results_file', '')}`."]
    return "\n".join(L) + "\n"
