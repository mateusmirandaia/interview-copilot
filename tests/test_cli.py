"""Command line: help, simulate and check in a subprocess against the mock API; eval passthrough."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import ROOT
from interview_copilot import cli


def run_cli(*args: str, env: dict[str, str] | None = None,
            timeout: float = 60) -> subprocess.CompletedProcess:
    full_env = dict(os.environ)
    full_env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + full_env.get("PYTHONPATH", "")
    full_env["PYTHONIOENCODING"] = "utf-8"
    full_env.update(env or {})
    return subprocess.run([sys.executable, "-m", "interview_copilot", *args], cwd=ROOT, env=full_env,
                          capture_output=True, text=True, encoding="utf-8", timeout=timeout)


def mock_env(mock_api) -> dict[str, str]:
    return {"ANTHROPIC_API_KEY": "test-key", "ANTHROPIC_BASE_URL": mock_api.url,
            "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost", "DEEPGRAM_API_KEY": ""}


def test_help_lists_every_command():
    r = run_cli("--help")
    assert r.returncode == 0, r.stderr
    for command in cli.COMMANDS:
        assert command in r.stdout
    assert run_cli("--version").stdout.strip().startswith("interview-copilot ")


def test_eval_help_comes_from_the_runner():
    r = run_cli("eval", "--help")
    assert r.returncode == 0, r.stderr
    for option in ("--round", "--compare-with", "--ids", "--no-judge", "--rejudge", "--judge-model",
                   "--parallel"):
        assert option in r.stdout


def test_unknown_argument_is_an_error(capsys: pytest.CaptureFixture[str]):
    with pytest.raises(SystemExit):
        cli.main(["simulate", "--nope"])


def test_simulate_without_key(profile: Path):
    r = run_cli("simulate", "hello", "--profile", str(profile), env={"ANTHROPIC_API_KEY": ""})
    assert r.returncode == 1 and "ANTHROPIC_API_KEY" in r.stderr


def test_simulate_against_mock(mock_api, profile: Path):
    r = run_cli("simulate", "How do you use pie test?", "--profile", str(profile), env=mock_env(mock_api))
    assert r.returncode == 0, r.stderr + r.stdout
    out = r.stdout
    assert "Profile: Sam Lee (Backend Engineer)" in out
    assert "QUESTION: How do you use pie test?" in out
    assert "TRANSLATION: Pergunta traduzida." in out
    assert "INTENT: saber se você mede antes de otimizar" in out
    assert "SUGGESTED ANSWER" in out and "I would start by measuring" in out
    assert "time: translation started" in out
    kinds = [r.kind for r in mock_api.requests]
    assert kinds.count("warmup") == 1 and "translation" in kinds and "answer" in kinds
    assert mock_api.of_kind("translation")[0].body["messages"][0]["content"] == "How do you use pytest?"


def test_check_without_key(profile: Path):
    r = run_cli("check", "--profile", str(profile), "-v", env={"ANTHROPIC_API_KEY": ""})
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "[--] ANTHROPIC_API_KEY" in out
    assert "Sam Lee · Backend Engineer · native language: Spanish" in out
    assert "ready answers: 2 from 05-ready-answers/ready-answers.md" in out
    assert "vocabulary.txt: 3 term(s)" in out
    assert "(estimated)" in out
    assert "04-skills/sub/go.md" in out              # -v lists files
    assert "Skipping live questions" in out


def test_check_against_mock(mock_api, profile: Path):
    r = run_cli("check", "--profile", str(profile), env=mock_env(mock_api))
    assert r.returncode == 0, r.stderr + r.stdout
    assert "cached context: 4,321 tokens (exact)" in r.stdout
    assert r.stdout.count("Q: ") == len(cli.CHECK_QUESTIONS)
    assert "prompt caching:" in r.stdout
    assert len(mock_api.of_kind("count_tokens")) == 1
    assert len(mock_api.of_kind("answer")) == len(cli.CHECK_QUESTIONS)


def test_check_missing_profile(tmp_path: Path):
    r = run_cli("check", "--profile", str(tmp_path / "nope"), env={"ANTHROPIC_API_KEY": ""})
    assert r.returncode == 1 and "profile folder not found" in r.stdout


def test_eval_passes_options_to_the_runner(monkeypatch: pytest.MonkeyPatch, profile: Path):
    from interview_copilot.evals import runner

    seen = {}

    def fake_main(argv, settings):
        seen.update(argv=argv, profile=settings.profile_path)
        return 3

    monkeypatch.setattr(runner, "main", fake_main)
    code = cli.main(["eval", "--round", "v2", "--ids", "1,2", "--no-judge", "--profile", str(profile)])
    assert code == 3
    assert seen["argv"] == ["--round", "v2", "--ids", "1,2", "--no-judge"]
    assert seen["profile"] == profile
