"""Anthropic API calls: translation, answer suggestion, ready-answer check and research.

- Translation and suggestion run in PARALLEL, both streaming, as soon as a question ends.
- The static context (generic instructions + profile + ready-answer catalog) goes in ``system``
  with ``cache_control``: from the second call on only the question is processed from scratch.
  The cache is warmed when the app starts.
- When the question matches a ready answer, the model only returns its ID (``READY: 3``); the app
  shows the text from the file. Before it is shown, a quick "same subject?" check runs; if it
  fails, the answer is regenerated with ready answers forbidden. Every check is logged to
  ``logs/answer_selection.jsonl``.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..knowledge.vocabulary import apply_replacements
from .parsing import parse_suggestion
from .prompts import (
    CHECK_SYSTEM,
    CHECK_USER,
    FORCE_NEW_ANSWER,
    build_research_request,
    build_system_prompt,
    build_translate_system,
    fill,
)

if TYPE_CHECKING:
    from ..knowledge.loader import Knowledge
    from ..settings import Settings


@dataclass
class Source:
    """A documentation page cited (or found) by the research call."""

    title: str
    url: str


@dataclass
class Turn:
    """One interviewer question and what the model answered."""

    question: str
    raw: str = ""
    check: dict[str, Any] | None = None   # ready-answer check decision, if one ran


@dataclass
class EngineStats:
    """Token usage accumulated over all calls."""

    cache_read: int = 0
    cache_write: int = 0
    input_tokens: int = 0
    calls: int = 0


def _get(obj: Any, key: str, default: Any = None) -> Any:
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def merge_sources(a: list[Source], b: list[Source]) -> list[Source]:
    """``a`` followed by the items of ``b`` whose URL is not in ``a`` yet."""
    out = list(a)
    for s in b:
        if all(s.url != x.url for x in out):
            out.append(s)
    return out


def extract_sources(content: Any) -> list[Source]:
    """Sources cited in the text blocks; if none are cited, the first 3 search results."""
    cited: list[Source] = []
    found: list[Source] = []
    for block in content or []:
        btype = _get(block, "type")
        if btype == "text":
            for c in _get(block, "citations") or []:
                url = _get(c, "url")
                if url:
                    cited.append(Source(_get(c, "title") or url, url))
        elif btype == "web_search_tool_result":
            res = _get(block, "content")
            if isinstance(res, list):
                for item in res:
                    url = _get(item, "url")
                    if url:
                        found.append(Source(_get(item, "title") or url, url))
    return merge_sources([], cited or found[:3])


def search_error(content: Any) -> str | None:
    """Error message of a failed web search tool result, if any."""
    for block in content or []:
        if _get(block, "type") == "web_search_tool_result":
            res = _get(block, "content")
            if not isinstance(res, list):
                code = _get(res, "error_code")
                if code:
                    return f"web search tool error: {code}"
    return None


class CopilotEngine:
    """Streams answers for interviewer questions, grounded in one profile."""

    def __init__(self, settings: Settings, knowledge: Knowledge,
                 on_status: Callable[[str], None] = print):
        import anthropic

        if not settings.anthropic_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set (environment variable or .env file).")
        self.settings = settings
        self.knowledge = knowledge
        a = settings.ai
        self.client = anthropic.Anthropic(api_key=settings.anthropic_key, max_retries=1, timeout=20)
        self.model = str(a.get("model", "claude-haiku-5-5"))
        self.effort = a.get("effort", "low")
        self.disable_thinking = bool(a.get("disable_thinking", True))
        self.max_answer = int(a.get("max_tokens_answer", 800))
        self.max_translation = int(a.get("max_tokens_translation", 300))
        self.history_turns = int(a.get("history_turns", 3))
        self.check_ready = bool(a.get("check_ready_answers", True))
        cache: dict[str, str] = {"type": "ephemeral"}
        if a.get("cache_ttl", "5m") == "1h":
            cache["ttl"] = "1h"
        self.system_blocks: list[dict[str, Any]] = [
            {"type": "text", "text": build_system_prompt(knowledge, settings)},
            {"type": "text", "text": knowledge.context_block() + "\n" + knowledge.catalog(),
             "cache_control": cache},
        ]
        self.translate_system = build_translate_system(knowledge)
        self.research_cfg = dict(settings.research)
        self.log_path: Path = settings.logs_dir / "answer_selection.jsonl"
        self.history: list[Turn] = []
        self.stats = EngineStats()
        self.on_status = on_status
        self._gen = 0
        self._lock = threading.Lock()

    # ---- shared parameters ----------------------------------------------------------------
    def _extra(self) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if self.effort:
            body["output_config"] = {"effort": self.effort}
        if self.disable_thinking:
            body["thinking"] = {"type": "disabled"}
        return body

    def _record_usage(self, msg: Any) -> None:
        u = getattr(msg, "usage", None)
        if not u:
            return
        self.stats.calls += 1
        self.stats.cache_read += getattr(u, "cache_read_input_tokens", 0) or 0
        self.stats.cache_write += getattr(u, "cache_creation_input_tokens", 0) or 0
        self.stats.input_tokens += getattr(u, "input_tokens", 0) or 0

    def normalize(self, question: str) -> str:
        """Apply the profile's transcript replacements (always the first step)."""
        return apply_replacements(question or "", self.knowledge.replacements)

    def build_user_message(self, question: str) -> str:
        """Recent questions (for context) + the current utterance."""
        parts: list[str] = []
        recent = self.history[-self.history_turns:] if self.history_turns else []
        if recent:
            parts.append("<recent_conversation>")
            parts += [f"Interviewer: {t.question}" for t in recent]
            parts.append("</recent_conversation>")
        parts.append(f"<interviewer_said>{question}</interviewer_said>")
        return "\n".join(parts)

    def _next_gen(self) -> int:
        with self._lock:
            self._gen += 1
            return self._gen

    # ---- cache warm-up --------------------------------------------------------------------
    def warm_cache(self) -> None:
        """Write the static context to the prompt cache (1-token call)."""
        t0 = time.perf_counter()
        try:
            msg = self.client.messages.create(
                model=self.model, max_tokens=1, system=self.system_blocks,
                messages=[{"role": "user", "content": "<interviewer_said>ping</interviewer_said>"}],
                extra_body=self._extra())
            self._record_usage(msg)
            u = msg.usage
            self.on_status(
                f"AI ready ({self.model}) in {time.perf_counter() - t0:.1f}s · cache written "
                f"{getattr(u, 'cache_creation_input_tokens', 0) or 0} / read "
                f"{getattr(u, 'cache_read_input_tokens', 0) or 0} tokens")
        except Exception as e:  # noqa: BLE001 - shown in the status bar
            self.on_status(f"AI warm-up failed: {e}")

    # ---- streaming ------------------------------------------------------------------------
    def _stream(self, *, system: Any, user: str, max_tokens: int, on_text: Callable[[str], None],
                gen: int) -> tuple[str, str | None]:
        """Return ``(text, stop_reason)``; stop_reason is ``'cancelled'`` if a newer question arrived."""
        acc = ""
        with self.client.messages.stream(
                model=self.model, max_tokens=max_tokens, system=system,
                messages=[{"role": "user", "content": user}], extra_body=self._extra()) as stream:
            for text in stream.text_stream:
                if gen != self._gen:
                    return acc, "cancelled"
                acc += text
                on_text(acc)
            final = stream.get_final_message()
        self._record_usage(final)
        stop = getattr(final, "stop_reason", None)
        if stop == "refusal":
            acc += "\n- (the AI declined this request)"
            on_text(acc)
        return acc, stop

    # ---- ready-answer check ---------------------------------------------------------------
    def check_ready_answer(self, question: str, answer_id: str) -> dict[str, Any]:
        """Quick check: do the question and the ready answer's title cover the same subject?

        On API errors the ready answer is kept. The decision is appended to :attr:`log_path`.
        """
        ra = self.knowledge.ready_answers.get(answer_id)
        title = ra.title if ra else answer_id
        t0 = time.perf_counter()
        same, raw = True, ""
        try:
            msg = self.client.messages.create(
                model=self.model, max_tokens=5, system=CHECK_SYSTEM,
                messages=[{"role": "user", "content": fill(CHECK_USER, question=question, title=title)}],
                extra_body=self._extra())
            self._record_usage(msg)
            raw = "".join(getattr(b, "text", "") for b in msg.content).strip()
            same = raw.lower().startswith("y")
        except Exception as e:  # noqa: BLE001 - keep the ready answer on errors
            raw = f"error: {e}"
        decision = {
            "time": dt.datetime.now().isoformat(timespec="seconds"),
            "question": question,
            "ready_answer": answer_id,
            "title": title,
            "same_subject": same,
            "check_reply": raw,
            "decision": "use ready answer" if same else "generate new answer",
            "elapsed_s": round(time.perf_counter() - t0, 2),
        }
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(decision, ensure_ascii=False) + "\n")
        except OSError:
            pass
        return decision

    # ---- answer ---------------------------------------------------------------------------
    def answer(self, question: str, *, on_translation: Callable[[str], None],
               on_suggestion: Callable[[str], None], on_first_content: Callable[[float], None],
               on_suggestion_done: Callable[[str | None], None] = lambda stop: None,
               on_done: Callable[[], None] = lambda: None,
               on_error: Callable[[str], None] = print, suggest: bool = True) -> None:
        """Start translation and (optionally) the suggestion in parallel. Does not block.

        ``on_suggestion`` receives the accumulated raw text (use ``parse_suggestion``).
        ``on_first_content`` fires with ``perf_counter()`` when the first useful content can be
        shown (the ready answer, after its check, or the first words of a new answer).
        ``on_suggestion_done`` receives the stop reason (``end_turn``, ``max_tokens``,
        ``cancelled``, ``error``...). ``on_done`` fires when every call finished.
        """
        question = self.normalize(question)
        gen = self._next_gen()
        user = self.build_user_message(question)
        turn = Turn(question)
        self.history.append(turn)
        pending = [2 if suggest else 1]
        done_lock = threading.Lock()

        def finish() -> None:
            with done_lock:
                pending[0] -= 1
                if pending[0] == 0:
                    on_done()

        def run_translation() -> None:
            try:
                self._stream(system=self.translate_system, user=question,
                             max_tokens=self.max_translation, on_text=on_translation, gen=gen)
            except Exception as e:  # noqa: BLE001
                on_error(f"Translation: {e}")
            finally:
                finish()

        def run_suggestion() -> None:
            first = [False]
            held = [False]   # ready answer held back until the "same subject?" check passes

            def show(acc: str) -> None:
                if not first[0] and parse_suggestion(acc).has_content:
                    first[0] = True
                    on_first_content(time.perf_counter())
                on_suggestion(acc)

            def on_text(acc: str) -> None:
                if held[0]:
                    return
                if self.check_ready and parse_suggestion(acc).model_id:
                    held[0] = True
                    return
                show(acc)

            stop: str | None = None
            try:
                turn.raw, stop = self._stream(system=self.system_blocks, user=user,
                                              max_tokens=self.max_answer, on_text=on_text, gen=gen)
                s = parse_suggestion(turn.raw, complete=True)
                if held[0] and s.model_id and stop != "cancelled" and gen == self._gen:
                    turn.check = self.check_ready_answer(question, s.model_id)
                    if turn.check["same_subject"]:
                        show(turn.raw)
                    else:
                        turn.raw, stop = self._stream(system=self.system_blocks,
                                                      user=user + FORCE_NEW_ANSWER,
                                                      max_tokens=self.max_answer, on_text=show, gen=gen)
                elif held[0] and stop != "cancelled" and gen == self._gen:
                    show(turn.raw)
            except Exception as e:  # noqa: BLE001
                stop = "error"
                on_error(f"Suggestion: {e}")
            finally:
                on_suggestion_done(stop)
                finish()

        threading.Thread(target=run_translation, daemon=True, name="ai-translate").start()
        if suggest:
            threading.Thread(target=run_suggestion, daemon=True, name="ai-suggest").start()

    # ---- research (only on the hotkey) ----------------------------------------------------
    def research(self, question: str, *, on_text: Callable[[str], None],
                 on_done: Callable[[str, str | None, list[Source]], None],
                 on_error: Callable[[str], None] = print) -> None:
        """Redo the answer using the API web search tool, restricted to the profile's domains.

        Does not block. ``on_done(raw, stop_reason, sources)``.
        """
        question = self.normalize(question)
        gen = self._next_gen()
        r = self.research_cfg
        model = r.get("model") or self.model
        domains = list(self.knowledge.research_domains)
        tool: dict[str, Any] = {"type": r.get("tool_version", "web_search_20250305"), "name": "web_search",
                                "max_uses": int(r.get("max_uses", 3))}
        if domains:
            tool["allowed_domains"] = domains

        def run() -> None:
            acc, stop, sources = "", None, []
            final = None
            messages: list[dict[str, Any]] = [
                {"role": "user", "content": build_research_request(question, domains)}]
            try:
                for _ in range(3):   # pause_turn: the server may ask to continue
                    with self.client.messages.stream(
                            model=model, max_tokens=int(r.get("max_tokens", 1500)),
                            system=self.system_blocks, messages=messages, tools=[tool],
                            extra_body=self._extra(), timeout=float(r.get("timeout_s", 60))) as st:
                        if acc and not acc.endswith("\n"):
                            acc += "\n"
                        for text in st.text_stream:
                            if gen != self._gen:
                                on_done(acc, "cancelled", sources)
                                return
                            acc += text
                            on_text(acc)
                        final = st.get_final_message()
                    self._record_usage(final)
                    sources = merge_sources(sources, extract_sources(final.content))
                    stop = getattr(final, "stop_reason", None)
                    if stop != "pause_turn":
                        break
                    messages = messages + [{"role": "assistant", "content": final.content}]
                err = search_error(final.content if final is not None else None)
                if err:
                    on_error(f"Research: {err}")
            except Exception as e:  # noqa: BLE001
                stop = "error"
                on_error(f"Research: {e}")
            on_done(acc, stop, sources)

        threading.Thread(target=run, daemon=True, name="ai-research").start()

    def cancel(self) -> None:
        """Abandon any answer in progress (its callbacks stop firing)."""
        self._next_gen()
