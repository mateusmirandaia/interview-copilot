"""Command line: ``python -m interview_copilot <command>`` (``run`` when no command is given)."""

from __future__ import annotations

import argparse
import importlib.util
import os
import queue
import sys
import threading
import time
import wave
from collections.abc import Callable

from . import __version__
from .knowledge.loader import KINDS, Knowledge
from .settings import Settings, load_settings

DEFAULT_QUESTION = "Could you give me a quick introduction about yourself?"
CHECK_QUESTIONS = [
    "Hi, thanks for joining. Could you give me a quick introduction about yourself?",
    "Why are you interested in this role?",
    "Tell me about a challenging project you worked on.",
    "Great, so let me tell you a bit about the project first.",
]
COMMANDS = ("run", "simulate", "check", "devices", "test-audio", "mvp", "download-docs", "eval")


# ---- helpers -----------------------------------------------------------------------------------
def _load(args: argparse.Namespace) -> tuple[Settings, Knowledge]:
    settings = load_settings(getattr(args, "settings", None))
    if getattr(args, "profile", None):
        settings.set_profile(args.profile)
    return settings, Knowledge.load(settings.profile_path)


def _require_key(settings: Settings) -> bool:
    if settings.anthropic_key:
        return True
    print("ANTHROPIC_API_KEY is not set. Put it in the environment or in a .env file at the repo root.",
          file=sys.stderr)
    return False


def _require_profile(knowledge: Knowledge) -> bool:
    if knowledge.profile.path.is_dir():
        return True
    print(f"Profile folder not found: {knowledge.profile.path}", file=sys.stderr)
    return False


def _printer() -> Callable[..., None]:
    lock = threading.Lock()

    def out(text: str = "", end: str = "\n") -> None:
        with lock:
            print(text, end=end, flush=True)

    return out


# ---- run / simulate ----------------------------------------------------------------------------
def _run_window(settings: Settings, knowledge: Knowledge, with_audio: bool, question: str | None,
                research: bool = False) -> int:
    from .app import CopilotApp, start_global_hotkeys
    from .ui.overlay import Overlay

    events: queue.Queue[tuple] = queue.Queue()
    app = CopilotApp(settings, knowledge, events, with_audio=with_audio)
    overlay = Overlay(settings, events, app.actions(), ready_answers=app.ready_answers)
    start_global_hotkeys(settings, events, app)
    app.start()
    if question:
        app.simulate(question)
        if research:
            threading.Timer(8.0, app.action_research).start()
    overlay.run()
    app.stop()
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Overlay window + live audio."""
    settings, knowledge = _load(args)
    if not (_require_key(settings) and _require_profile(knowledge)):
        return 1
    return _run_window(settings, knowledge, with_audio=True, question=None)


def cmd_simulate(args: argparse.Namespace) -> int:
    """Answer a typed question without audio (terminal, or the window with --ui)."""
    settings, knowledge = _load(args)
    if not (_require_key(settings) and _require_profile(knowledge)):
        return 1
    question = " ".join(args.question).strip() or DEFAULT_QUESTION
    if args.ui:
        return _run_window(settings, knowledge, with_audio=False, question=question, research=args.research)
    from .console import ask_and_print, build_engine, research_and_print

    engine = build_engine(settings, knowledge)
    engine.warm_cache()
    print(f"\nQUESTION: {question}")
    ask_and_print(engine, question)
    if args.research:
        research_and_print(engine, question)
    return 0


# ---- check -------------------------------------------------------------------------------------
def _line(ok: bool | None, text: str) -> None:
    mark = {True: "[OK]", False: "[--]", None: "[  ]"}[ok]
    print(f"{mark} {text}")


def cmd_check(args: argparse.Namespace) -> int:
    """Readable checklist of keys, profile, dependencies and a few live sample questions."""
    settings, knowledge = _load(args)
    p = knowledge.profile
    print(f"Interview Copilot {__version__} - setup check\n")
    print("Keys")
    _line(bool(settings.anthropic_key), "ANTHROPIC_API_KEY")
    _line(bool(settings.deepgram_key), "DEEPGRAM_API_KEY (optional; without it, local Whisper is used)")

    print(f"\nProfile: {p.path}")
    if not p.path.is_dir():
        _line(False, "profile folder not found (set [profile] path or use --profile)")
        return 1
    _line((p.path / "profile.toml").is_file(), f"profile.toml · {p.name} · {p.target_role} · "
                                               f"native language: {p.native_language}")
    for number, kind in KINDS.items():
        folders = sorted(p.path.glob(f"{number}-*"))
        docs = knowledge.documents_of(kind)
        label = folders[0].name if folders else f"{number}-* ({kind})"
        _line(bool(docs) if kind != "official_docs" else (True if docs else None),
              f"{label}: {len(docs)} file(s)")
        if args.verbose:
            for d in docs:
                print(f"       {d.path.as_posix()}  ({len(d.text):,} characters)")
    ra_file = knowledge.ready_answers_file
    _line(bool(knowledge.ready_answers),
          f"ready answers: {len(knowledge.ready_answers)} from "
          f"{ra_file.relative_to(p.path).as_posix() if ra_file else '(no file)'}")
    for ra in list(knowledge.ready_answers.values())[: 50 if args.verbose else 5]:
        print(f"       {ra.id} | {ra.title}")
    _line(bool(knowledge.vocabulary), f"vocabulary.txt: {len(knowledge.vocabulary)} term(s)")
    _line(True if knowledge.replacements else None,
          f"transcript replacements: {len(knowledge.replacements)}")
    _line(True if knowledge.research_domains else None,
          f"research domains: {', '.join(knowledge.research_domains) or '(unrestricted web search)'}")
    links = p.path / "07-official-docs" / "links.txt"
    if links.is_file() and not knowledge.documents_of("official_docs"):
        _line(None, "07-official-docs/links.txt exists: run `python -m interview_copilot download-docs`")
    _line(True if (p.path / "evals" / "questions.json").is_file() else None, "evals/questions.json")

    from .console import count_tokens

    tokens, exact = count_tokens(settings, knowledge)
    warn = int(settings.knowledge.get("warn_tokens", 100_000))
    _line(tokens <= warn, f"cached context: {tokens:,} tokens {'(exact)' if exact else '(estimated)'} · "
                          f"warning above {warn:,}")
    _line(int(settings.ai.get("max_tokens_answer", 0)) >= 600,
          f"[ai] max_tokens_answer = {settings.ai.get('max_tokens_answer')} (600 or more recommended)")

    print("\nDependencies")
    on_windows = sys.platform == "win32"
    _line(importlib.util.find_spec("pyaudiowpatch") is not None if on_windows else None,
          "pyaudiowpatch (audio capture, Windows only)")
    _line(importlib.util.find_spec("pynput") is not None, "pynput (global hotkeys)")
    _line(importlib.util.find_spec("tkinter") is not None, "tkinter (overlay window)")
    if importlib.util.find_spec("faster_whisper") is not None:
        from .stt.whisper import cuda_available

        gpu = cuda_available()
        _line(True, f"faster-whisper installed · CUDA GPU: {'yes' if gpu else 'no (CPU is slower)'}")
    else:
        _line(None, "faster-whisper not installed (fine when using Deepgram)")

    if not settings.anthropic_key:
        print("\nSkipping live questions (no ANTHROPIC_API_KEY).")
        return 0
    from .console import ask_and_print, build_engine

    print("\nLive sample questions")
    engine = build_engine(settings, knowledge, out=lambda s: print("    " + s))
    engine.warm_cache()
    for q in CHECK_QUESTIONS:
        print(f"\n  Q: {q}")
        ask_and_print(engine, q, lambda t: print("  " + t))
    s = engine.stats
    _line(s.cache_read > 0, f"prompt caching: {s.cache_read} tokens read from cache, {s.cache_write} written")
    return 0


# ---- audio tools -------------------------------------------------------------------------------
def cmd_devices(args: argparse.Namespace) -> int:
    """List WASAPI loopback devices."""
    from .audio.capture import default_loopback_device, list_loopback_devices

    try:
        default = default_loopback_device()
        devices = list_loopback_devices()
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 1
    print(f"DEFAULT: {default['name'] if default else '(none)'}\n")
    for d in devices:
        print(f"[{d['index']}] {d['name']}  ({int(d['defaultSampleRate'])} Hz, {d['maxInputChannels']} ch)")
    print("\nTo use another one, copy part of its name to [audio] device_name in config/settings.local.toml")
    return 0


def cmd_test_audio(args: argparse.Namespace) -> int:
    """Record system audio to logs/capture_test.wav with a live level meter."""
    from .audio.capture import TARGET_RATE, AudioChunk, LoopbackCapture

    settings = load_settings(getattr(args, "settings", None))
    chunks: list[bytes] = []

    def on_chunk(c: AudioChunk) -> None:
        chunks.append(c.pcm16)
        bar = "#" * min(40, int(c.rms * 400))
        print(f"\rlevel {c.rms:.3f} {bar:<40}", end="", flush=True)

    cap = LoopbackCapture(on_chunk, str(settings.audio.get("device_name", "")),
                          int(settings.audio.get("chunk_ms", 50)))
    print(f"Recording {args.seconds:.0f} s of system audio. Play a video now...")
    cap.start()
    time.sleep(args.seconds)
    cap.stop()
    print(f"\nDevice: {cap.device_label}")
    if cap.error:
        return 1
    out = settings.logs_dir / "capture_test.wav"
    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(TARGET_RATE)
        w.writeframes(b"".join(chunks))
    print(f"Saved {out} ({sum(len(c) for c in chunks) / 2 / TARGET_RATE:.1f} s). "
          "It should contain only the computer sound, not your voice.")
    return 0


def cmd_mvp(args: argparse.Namespace) -> int:
    """Terminal prototype: capture + speech-to-text + translation (+ answers with --suggest)."""
    from .audio.capture import LoopbackCapture
    from .console import ask_and_print, build_engine
    from .stt import Utterance, make_transcriber

    settings, knowledge = _load(args)
    if not _require_key(settings):
        return 1
    if os.name == "nt":
        os.system("")   # enable ANSI escape codes in the Windows console
    clear_line = "\r\033[K"
    out = _printer()
    engine = build_engine(settings, knowledge, out)
    if args.suggest:
        engine.warm_cache()

    def handle(u: Utterance) -> None:
        out(f"{clear_line}\nQUESTION: {u.text}")
        out(f"   pause detected {u.t_detected - u.t_speech_end:.2f}s after the speech")
        ask_and_print(engine, u.text, out, t_ref=u.t_speech_end, suggest=args.suggest)

    stt = make_transcriber(settings, knowledge.vocabulary,
                           lambda text: out(f"{clear_line}... {text[-110:]}", end=""),
                           lambda u: threading.Thread(target=handle, args=(u,), daemon=True).start(),
                           lambda s: out(f"{clear_line}[STT] {s}"))
    cap = LoopbackCapture(stt.feed, str(settings.audio.get("device_name", "")),
                          int(settings.audio.get("chunk_ms", 50)))
    stt.start()
    cap.start()
    time.sleep(1.5)
    out(f"[AUDIO] {cap.device_label}\n[STT] {stt.name}\nListening to the computer audio... Ctrl+C to quit.\n")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        cap.stop()
        stt.stop()
    return 0


# ---- docs / evals ------------------------------------------------------------------------------
def cmd_download_docs(args: argparse.Namespace) -> int:
    """Download 07-official-docs/links.txt into markdown files, then report the context size."""
    from .console import count_tokens
    from .knowledge.docs_downloader import download_docs

    settings, knowledge = _load(args)
    if not _require_profile(knowledge):
        return 1
    saved = download_docs(knowledge.profile.path)
    knowledge = Knowledge.load(knowledge.profile.path)
    tokens, exact = count_tokens(settings, knowledge)
    warn = int(settings.knowledge.get("warn_tokens", 100_000))
    print(f"Total cached context: {tokens:,} tokens {'(exact)' if exact else '(estimated)'}")
    if tokens > warn:
        print(f"\nWARNING: the context is above {warn:,} tokens. The first answer gets slower and "
              "long-prompt pricing may apply. Delete the least useful pages from 07-official-docs/.")
    return 0 if saved else 1


def cmd_eval(args: argparse.Namespace, extra: list[str]) -> int:
    """Delegate to ``interview_copilot.evals.runner.main(argv, settings)``."""
    settings = load_settings(getattr(args, "settings", None))
    if getattr(args, "profile", None):
        settings.set_profile(args.profile)
    try:
        from .evals import runner
    except ModuleNotFoundError as e:
        if e.name and e.name.startswith("interview_copilot.evals"):
            print("The evals module (interview_copilot.evals.runner) is not available in this install.",
                  file=sys.stderr)
            return 1
        raise
    result = runner.main(extra, settings)
    return int(result or 0)


# ---- parser ------------------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    """Argument parser with every subcommand."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--profile", metavar="PATH", default=argparse.SUPPRESS,
                        help="profile folder (overrides [profile] path)")
    common.add_argument("--settings", metavar="PATH", default=argparse.SUPPRESS,
                        help="settings file (default: config/settings.toml)")

    parser = argparse.ArgumentParser(
        prog="interview-copilot", parents=[common],
        description="Real-time AI copilot for job interviews in English.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="command")

    sub.add_parser("run", parents=[common], help="overlay window + live audio (default)")

    p = sub.add_parser("simulate", parents=[common], help="answer a typed question, no audio")
    p.add_argument("question", nargs="*", help=f'question text (default: "{DEFAULT_QUESTION}")')
    p.add_argument("--ui", action="store_true", help="open the window and inject the question")
    p.add_argument("--research", action="store_true", help="also run the documentation search")

    p = sub.add_parser("check", parents=[common], help="check keys, profile, dependencies and latency")
    p.add_argument("-v", "--verbose", action="store_true", help="list every file and ready answer")

    sub.add_parser("devices", parents=[common], help="list WASAPI loopback devices")

    p = sub.add_parser("test-audio", parents=[common], help="record system audio to logs/capture_test.wav")
    p.add_argument("--seconds", type=float, default=8.0, help="recording length (default 8)")

    p = sub.add_parser("mvp", parents=[common], help="terminal prototype: capture + STT + translation")
    p.add_argument("--suggest", action="store_true", help="also print answers")

    sub.add_parser("download-docs", parents=[common], help="download 07-official-docs/links.txt pages")

    sub.add_parser("eval", parents=[common], help="run the evals (extra options go to the eval runner)",
                   add_help=False)
    return parser


HANDLERS: dict[str, Callable[[argparse.Namespace], int]] = {
    "run": cmd_run,
    "simulate": cmd_simulate,
    "check": cmd_check,
    "devices": cmd_devices,
    "test-audio": cmd_test_audio,
    "mvp": cmd_mvp,
    "download-docs": cmd_download_docs,
}


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args, extra = parser.parse_known_args(argv)
    command = args.command or "run"
    try:
        if command == "eval":
            return cmd_eval(args, extra)
        if extra:
            parser.error(f"unrecognized arguments: {' '.join(extra)}")
        return HANDLERS[command](args)
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
