"""Settings: defaults + local override, .env loading, profile override."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from interview_copilot import settings as settings_mod
from interview_copilot.settings import Settings, deep_merge, load_dotenv, load_settings


def test_deep_merge_is_recursive_and_pure():
    base = {"ai": {"model": "a", "effort": "low"}, "x": 1}
    out = deep_merge(base, {"ai": {"model": "b"}, "y": 2})
    assert out == {"ai": {"model": "b", "effort": "low"}, "x": 1, "y": 2}
    assert base["ai"]["model"] == "a"


def test_default_settings_load(tmp_path: Path):
    # a copy, so a developer's config/settings.local.toml does not change the result
    copy = tmp_path / "settings.toml"
    copy.write_bytes((settings_mod.DEFAULT_SETTINGS).read_bytes())
    s = load_settings(copy)
    assert s.ai["model"] == "claude-haiku-5-5"
    assert s.ai["answer_words_max"] == 80
    assert s.evals["judge_model"] == "claude-sonnet-5-5"
    assert s.evals["pitch_words_max"] == 100
    assert s.profile_path == (s.root / "profiles" / "example").resolve()
    assert s.logs_dir == s.root / "logs"
    assert s.section("missing") == {}


def test_local_override_is_merged(tmp_path: Path):
    (tmp_path / "settings.toml").write_text('[ai]\nmodel = "m1"\neffort = "low"\n[ui]\nwidth = 600\n')
    (tmp_path / "settings.local.toml").write_text('[ai]\nmodel = "m2"\n')
    s = load_settings(tmp_path / "settings.toml")
    assert s.ai == {"model": "m2", "effort": "low"}
    assert s.ui["width"] == 600
    assert s.source == tmp_path / "settings.toml"


def test_missing_settings_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_settings(tmp_path / "nope.toml")


def test_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    env = tmp_path / ".env"
    env.write_text(
        "# comment\n\nIC_TEST_A=plain\nexport IC_TEST_B='quoted # not a comment'\n"
        'IC_TEST_C="double"\nIC_TEST_D=value # inline comment\nIC_TEST_REAL=from-file\nnot a pair\n',
        encoding="utf-8")
    for k in ("IC_TEST_A", "IC_TEST_B", "IC_TEST_C", "IC_TEST_D"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("IC_TEST_REAL", "from-env")
    pairs = load_dotenv(env)
    assert pairs["IC_TEST_A"] == "plain"
    assert pairs["IC_TEST_B"] == "quoted # not a comment"
    assert pairs["IC_TEST_C"] == "double"
    assert pairs["IC_TEST_D"] == "value"
    assert os.environ["IC_TEST_A"] == "plain"
    assert os.environ["IC_TEST_REAL"] == "from-env"   # real variables win
    for k in ("IC_TEST_A", "IC_TEST_B", "IC_TEST_C", "IC_TEST_D"):
        monkeypatch.delenv(k, raising=False)
    assert load_dotenv(tmp_path / "missing.env") == {}


def test_load_settings_reads_repo_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fake_root = tmp_path / "repo"
    (fake_root / "config").mkdir(parents=True)
    (fake_root / "config" / "settings.toml").write_text("[ai]\nmodel = 'x'\n")
    (fake_root / ".env").write_text("IC_TEST_KEY=abc\n")
    monkeypatch.delenv("IC_TEST_KEY", raising=False)
    monkeypatch.setattr(settings_mod, "ROOT", fake_root)
    monkeypatch.setattr(settings_mod, "DEFAULT_SETTINGS", fake_root / "config" / "settings.toml")
    s = load_settings()
    assert s.ai["model"] == "x"
    assert os.environ["IC_TEST_KEY"] == "abc"
    monkeypatch.delenv("IC_TEST_KEY", raising=False)


def test_keys_come_from_environment(monkeypatch: pytest.MonkeyPatch):
    s = Settings({})
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    monkeypatch.setenv("DEEPGRAM_API_KEY", "")
    assert s.anthropic_key == "a"
    assert s.deepgram_key is None


def test_set_profile_and_resolve(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    s = Settings({"profile": {"path": "profiles/example"}}, root=tmp_path)
    assert s.profile_path == (tmp_path / "profiles" / "example").resolve()
    s.set_profile(tmp_path / "abs")
    assert s.profile_path == tmp_path / "abs"
    # relative: current directory first when it exists...
    (tmp_path / "cwd" / "mine").mkdir(parents=True)
    monkeypatch.chdir(tmp_path / "cwd")
    s.set_profile("mine")
    assert s.profile_path == (tmp_path / "cwd" / "mine").resolve()
    # ...otherwise relative to the repo root
    s.set_profile("profiles/other")
    assert s.profile_path == (tmp_path / "profiles" / "other").resolve()
    assert s.resolve("/x/y") == Path("/x/y")
