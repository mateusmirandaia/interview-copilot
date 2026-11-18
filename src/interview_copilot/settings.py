"""Settings: committed defaults + optional local overrides + secrets from the environment.

- ``config/settings.toml`` holds the defaults.
- ``config/settings.local.toml`` (optional, gitignored) is deep-merged on top.
- ``.env`` at the repo root is loaded into ``os.environ`` (real environment variables win).
- Every relative path is resolved against the repo root (the parent of ``src/``).
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SETTINGS = ROOT / "config" / "settings.toml"


def deep_merge(base: dict, override: dict) -> dict:
    """Return a new dict with ``override`` merged recursively on top of ``base``."""
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_dotenv(path: Path) -> dict[str, str]:
    """Load ``KEY=value`` lines from ``path`` into ``os.environ`` without overwriting real variables.

    Supports ``#`` comments, an optional ``export`` prefix and single/double quoted values.
    Returns the pairs that were read.
    """
    pairs: dict[str, str] = {}
    if not path.is_file():
        return pairs
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        if key:
            pairs[key] = value
            os.environ.setdefault(key, value)
    return pairs


class Settings:
    """Parsed settings. ``raw`` is the merged dict; properties give each section as a dict."""

    def __init__(self, raw: dict[str, Any], root: Path = ROOT, source: Path | None = None):
        self.raw = raw
        self.root = root
        self.source = source

    def section(self, name: str) -> dict[str, Any]:
        """Return a settings section (empty dict when missing)."""
        value = self.raw.get(name, {})
        return value if isinstance(value, dict) else {}

    @property
    def ai(self) -> dict[str, Any]:
        return self.section("ai")

    @property
    def research(self) -> dict[str, Any]:
        return self.section("research")

    @property
    def knowledge(self) -> dict[str, Any]:
        return self.section("knowledge")

    @property
    def stt(self) -> dict[str, Any]:
        return self.section("stt")

    @property
    def audio(self) -> dict[str, Any]:
        return self.section("audio")

    @property
    def ui(self) -> dict[str, Any]:
        return self.section("ui")

    @property
    def hotkeys(self) -> dict[str, Any]:
        return self.section("hotkeys")

    @property
    def evals(self) -> dict[str, Any]:
        return self.section("evals")

    def resolve(self, path: str | os.PathLike[str]) -> Path:
        """Resolve ``path`` against the repo root unless it is absolute."""
        p = Path(path).expanduser()
        return p if p.is_absolute() else (self.root / p).resolve()

    @property
    def profile_path(self) -> Path:
        """Absolute path of the active profile folder."""
        return self.resolve(self.section("profile").get("path", "profiles/example"))

    def set_profile(self, path: str | os.PathLike[str]) -> None:
        """Override the active profile (e.g. from ``--profile``).

        A relative path is tried against the current directory first, then the repo root.
        """
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = p.resolve() if p.exists() else self.root / p
        self.raw.setdefault("profile", {})["path"] = str(p)

    @property
    def logs_dir(self) -> Path:
        """Folder for runtime logs (``logs/`` at the repo root)."""
        return self.root / "logs"

    @property
    def anthropic_key(self) -> str | None:
        return os.environ.get("ANTHROPIC_API_KEY") or None

    @property
    def deepgram_key(self) -> str | None:
        return os.environ.get("DEEPGRAM_API_KEY") or None


def load_settings(path: str | os.PathLike[str] | None = None) -> Settings:
    """Load the defaults file (``path`` or ``config/settings.toml``) plus ``settings.local.toml`` next to it.

    Also loads ``.env`` from the repo root.
    """
    load_dotenv(ROOT / ".env")
    p = Path(path).expanduser() if path else DEFAULT_SETTINGS
    if not p.is_absolute():
        p = p.resolve() if p.exists() else ROOT / p
    if not p.is_file():
        raise FileNotFoundError(f"Settings file not found: {p}")
    with open(p, "rb") as f:
        raw = tomllib.load(f)
    local = p.with_name(p.stem + ".local" + p.suffix)
    if local.is_file():
        with open(local, "rb") as f:
            raw = deep_merge(raw, tomllib.load(f))
    return Settings(raw, ROOT, p)
