# Troubleshooting

Start with `python -m interview_copilot check`: it reports most setup problems in one run.

## Setup

| Symptom | Fix |
|---|---|
| `.\scripts\setup.ps1 cannot be loaded because running scripts is disabled on this system` | Allow local scripts for your user: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`. Or run once with `powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1` |
| `py : The term 'py' is not recognized` | The Python launcher is not installed. `setup.ps1` falls back to `python` automatically; to create the venv by hand use `python -m venv .venv` |
| `python` opens the Microsoft Store or prints "Python was not found" | Install Python 3.11+ from python.org (check "Add python.exe to PATH"), or turn off the `python.exe` alias in *Settings > Apps > App execution aliases* |
| `Python 3.x found, but 3.11 or newer is required` | Install Python 3.12 and run `setup.ps1` again |
| Packages "not found" after setup, or the wrong Python runs | Activate the venv first: `.\.venv\Scripts\Activate.ps1` (the prompt shows `(.venv)`). Or use `.\scripts\run.ps1`, which activates it for you |
| `ANTHROPIC_API_KEY` not found right after `setx` | `setx` only affects **new** terminals. Close and reopen PowerShell (and your editor). Alternatively, use a `.env` file at the repo root |
| `pyaudiowpatch` fails to install | It is Windows-only. On Linux/macOS you can still run tests, `check` and `simulate`, but not live audio |

## API errors

| Symptom | Fix |
|---|---|
| `400 invalid_request_error` on every call | Often means the **credit balance is too low**. Check *Billing* in the Anthropic Console. Read the full message: it names the cause |
| Error about `ttl` / cache control | Set `[ai] cache_ttl = "5m"` |
| Error about `thinking` or `effort` | Update the SDK: `pip install -U anthropic` |
| Research hotkey fails with a permission or "web search" error | Web search may be disabled for your organization. An admin can enable it in the Anthropic Console. Also check `[research] allowed_domains` in `profile.toml` |
| Footer shows **cache read 0** | The knowledge block is below the model's minimum cacheable size, the app was idle longer than the TTL, or the profile changed since the cache was written. A larger profile, `cache_ttl = "1h"` and restarting after edits fix it |
| "Large context" warning | The profile exceeds `[knowledge] warn_tokens`. Remove unused official docs or long skill files |

## Audio and transcription

| Symptom | Fix |
|---|---|
| Level meter flat in `test-audio` | Play a video, run `python -m interview_copilot devices`, and set part of the right device name in `[audio] device_name` (for example, your headset). The app captures the **output** device, not the microphone |
| Level meter moves when you talk | You picked a microphone-like device; choose the speakers/headset output instead |
| Questions are cut in the middle | Increase `[stt] pause_ms` to 900–1000 |
| Answers start too late after the question | Use Deepgram, lower `pause_ms` to 500–600, keep `effort = "low"` |
| Names or terms transcribed wrong | Add the correct spelling to the profile's `vocabulary.txt`; for recurring mistakes add a rule in `[transcript_replacements]`. Restart the app |
| Whisper does not detect speech | Lower `[stt.whisper] vad_threshold` (for example `0.005`) |
| Whisper is slow | Without an NVIDIA GPU, local transcription often exceeds the latency target. Use Deepgram (`DEEPGRAM_API_KEY`) |

## Overlay and answers

| Symptom | Fix |
|---|---|
| Global hotkeys do nothing | Run the terminal with the **same elevation** as the call app (both normal or both as administrator). Inside the overlay, `F7`–`F10` always work |
| "Answer cut off" warning | Increase `[ai] max_tokens_answer` (keep it at 600 or more) |
| A ready answer never appears for a question you prepared | Make sure the heading is `##` / `###` (or Heading 2/3 in `.docx`), is not in `exclude_headings`, and is phrased as the question. `check` lists the ready answers it found; `logs/answer_selection.jsonl` shows when the "same subject?" check rejected it |
| The wrong ready answer is chosen | Rephrase the heading as the exact question, split headings that cover two questions, and run the evals |
| Answers mix two stories | Fix the `Topic → case` table in `03-projects/projects.md` |
| Changes to profile files are ignored | Files are read once at startup. Restart the app |
