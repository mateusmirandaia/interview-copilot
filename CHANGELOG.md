# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [2.0.0] - 2026-11-18

First public release. A full rewrite of the personal prototype as a generic,
documented and tested open-source project.

### Added
- **Generic profiles ("knowledge packs")**: one folder per candidate under `profiles/`, with numbered
  folders for instructions, resume, projects, skills, ready answers, job and official docs, plus
  `profile.toml`, `vocabulary.txt` and `evals/questions.json`.
- Fictional example profile (`profiles/example`, Alex Morgan, Senior Python Backend Engineer) and an
  empty `profiles/_template`.
- Ready answers in Markdown (`##` / `###` headings) in addition to `.docx`.
- Per-profile native language for the translation and intent line, research domains and transcript
  replacements.
- Single CLI: `python -m interview_copilot run | simulate | check | devices | test-audio | mvp |
  download-docs | eval`, with global `--profile` and `--settings`.
- **Evals**: question sets per profile, keyword checks, LLM judge with a six-criteria rubric, automatic
  checks, markdown report, comparison between rounds (`--round`, `--compare-with`, `--ids`,
  `--no-judge`, `--rejudge`).
- Layered settings: `config/settings.toml` + gitignored `config/settings.local.toml`; `.env` support.
- Generic official-docs downloader driven by `07-official-docs/links.txt`.
- Configurable answer length (`answer_words_target`, `answer_words_max`) and an option to turn off the
  ready-answer check.
- Offline unit tests with a mock HTTP server, GitHub Actions CI (ruff + pytest, Python 3.11 / 3.12).
- PowerShell setup and run scripts; documentation (architecture, customizing, testing,
  troubleshooting) and a Portuguese README.

### Changed
- Package layout under `src/interview_copilot/` (audio, stt, knowledge, ai, ui, evals).
- Output markers renamed to `READY:` and `INTENT:` (the v1 markers are still accepted).
- All code, comments and UI strings in English.

### Removed
- Hard-coded paths and all personal content from the prototype.

## [1.0.0] - 2026 (not published)

Personal prototype for a single candidate: WASAPI loopback capture, Deepgram / faster-whisper
streaming transcription, Claude Haiku answers with prompt caching, ready answers from a `.docx`,
always-on-top overlay, on-demand documentation search, and a first version of the eval runner.
Portuguese-only and tied to one machine's folder layout.
