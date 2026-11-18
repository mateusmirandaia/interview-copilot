# Testing

There are four levels of testing: unit tests (offline, run in CI), smoke tests (one command each), an end-to-end session with a YouTube video, and evals (answer quality).

## Unit tests

```powershell
python -m pytest -q
ruff check .
```

- `pytest` and `ruff` are installed by `.\scripts\setup.ps1` (`pip install -e .[dev]`).
- **Fully offline.** The Anthropic client is pointed at a local mock HTTP server (`ANTHROPIC_BASE_URL` / `base_url`), so no key and no network are needed. The mock checks the request shape: model, `cache_control` on the knowledge block, `output_config.effort`, `thinking: disabled`, streaming.
- **Behind a proxy**, exclude the local mock: `$env:NO_PROXY="127.0.0.1"` (PowerShell) or `NO_PROXY=127.0.0.1 python -m pytest -q` (bash). The CI sets this already.
- **No audio libraries needed.** `pyaudiowpatch`, `pynput`, `faster-whisper` and `tkinter` are imported lazily, so every module imports on Linux.
- Covered areas: settings merge and `.env` loading, profile loading and the context block order, ready-answer parsing (`.md` and `.docx`, `clean_paragraph`), vocabulary and replacements, output parsing (including partial streams and v1 aliases), rendering, ready-answer check and forced regeneration, audio resampling, pause detection, Deepgram message parsing, the latency clock.

## Continuous integration

`.github/workflows/ci.yml` runs on every push and pull request: `ruff check` and `pytest` on Ubuntu with Python 3.11 and 3.12. Audio capture is the only part that cannot run there; it is covered by the smoke tests below on Windows.

## Smoke tests (Windows)

Run them in order after setup. Each one isolates one layer.

| Command | Checks | Expected |
|---|---|---|
| `python -m interview_copilot check` | Keys, profile files, ready answers, vocabulary, token count (exact with `count_tokens` when the key is set), 4 sample questions | All items OK; sample answers printed with timings |
| `python -m interview_copilot simulate "Tell me about yourself."` | Engine without audio: translation, intent, answer, timings | A ready answer for the example profile |
| `python -m interview_copilot simulate "How would you speed up a slow API?" --ui` | The overlay with an injected question | Window opens and shows the answer |
| `python -m interview_copilot simulate "..." --research` | Research path (web search on allowed domains) | Answer plus sources |
| `python -m interview_copilot devices` | WASAPI loopback devices | Your speakers / headset listed, default marked |
| `python -m interview_copilot test-audio` | Capture only: 8 s to `logs/capture_test.wav` with a live level meter | Meter moves with a video, stays flat when you talk into the mic |
| `python -m interview_copilot mvp` | Capture + STT + translation in the terminal | Interim text, then the question and its translation with timings |
| `python -m interview_copilot mvp --suggest` | Same, plus answers | Answers in the terminal |

## End-to-end with a YouTube video

1. Search YouTube for **"mock job interview questions and answers"**. For technical questions closer to the example profile, try "Python backend interview questions".
2. Start the app: `python -m interview_copilot run` (example profile, or `--profile profiles\me`).
3. Play the video at normal speed, with the browser as the audio output.
4. Check in the overlay:
   - the live line follows the speech;
   - each question appears with its translation and intent;
   - matching questions show a ready answer with its title; others show a new spoken answer;
   - the latency in the top-right corner stays green or yellow (under 3 s);
   - the footer shows the audio device, the STT provider, the profile size and cache tokens read.
5. Try the hotkeys: suggest (`Ctrl+Alt+S`), research (`Ctrl+Alt+D`), pause, clear, scroll.
6. Afterwards, read `logs/answer_selection.jsonl` to review which ready answers were accepted or rejected.

## Evals

Evals measure answer quality on a fixed question set, through the same engine the app uses (each question isolated, without conversation history).

```powershell
python -m interview_copilot eval                                   # all questions
python -m interview_copilot eval --ids 1,2,7                       # a subset
python -m interview_copilot eval --no-judge                        # answers + keyword checks only
python -m interview_copilot eval --rejudge                         # reuse saved answers, judge and report again
python -m interview_copilot eval --round v2 --compare-with results_v1.json
```

| Option | Effect |
|---|---|
| `--round NAME` | Names the run (default `v1`): writes `logs/evals/results_NAME.json`, `logs/evals/report_NAME.md` and `logs/evals/answer_selection_NAME.jsonl` without overwriting other rounds |
| `--compare-with FILE` | Adds a comparison section against a previous results file (path relative to `logs/evals/`; a missing file only prints a warning) |
| `--ids 1,2` | Runs only these question ids |
| `--no-judge` | Skips the LLM judge (faster, cheaper) |
| `--rejudge` | Reuses the saved answers of the same round and only re-runs the judge and the report |
| `--judge-model NAME` | Overrides `[evals] judge_model` |
| `--parallel N` | Parallel judge calls (questions are always generated one at a time, so latency stays accurate) |

The judge model and parallelism come from `[evals] judge_model` (`claude-sonnet-5-5`) and `[evals] parallel` (4). The judge receives the full context block, so it can verify numbers against your files and docs.

**Pass/fail.** An answer fails if it contains a `must_not_contain` word, cites more than one real case, gets `failed: true` from the judge, or is empty. Going over the word limit is reported but does not fail it. The word limit is `[ai] answer_words_max` (80); the introduction pitch may go to `[evals] pitch_words_max` (100). The pitch is question id 1, category "Pitch", a "Behavioral" question containing "yourself", or a ready answer titled like "yourself"/"introduction".

**Real-case detection.** Each `## <Case name>` section of `03-projects/projects.md` (except the "Topic → case" map) is a case. A case is detected in an answer by its name or by any word on its `- **Keywords:**` line. Add distinctive keywords when two cases share a company name.

**API errors.** If the first question fails with an API error, the run stops. A credit or authentication error (`400 invalid_request_error`, `401`) stops the remaining judge calls and is reported clearly; fix the key or the credit balance and rerun with `--rejudge`.

### Questions file

`profiles/<name>/evals/questions.json`:

```json
{"description": "Eval set for the example profile",
 "facts": ["Alex has eight years of Python experience"],
 "auto_fail": ["Claims experience with a cloud provider not in the resume"],
 "questions": [
   {"id": 1, "category": "Behavioral", "question": "Tell me about yourself.",
    "must_contain": [{"term": "8 years", "alternatives": ["eight years"]}],
    "must_not_contain": [{"description": "invented employer", "words": ["Google"]}],
    "equivalent_to": null}
 ]}
```

- `facts`: verified facts the judge must enforce.
- `auto_fail`: extra rules that fail an answer automatically.
- `must_contain`: each item passes if the term or any alternative appears (case-insensitive).
- `must_not_contain`: fails if any of the words appear.
- `equivalent_to`: for a mis-transcribed variant, the id of the original question; the report compares the two.

### Report sections

In this order:

- **Comparison with the previous round** (only with `--compare-with`): passed, average total, average per criterion, latency, improved and worsened questions with reasons.
- **Automatic checks (should all be zero)**: more than one real case, over the word limit, forbidden words, unsuitable ready answers, and how many ready answers the "same subject?" check used or rejected.
- **Answer length**: average, maximum and the answers over the limit, with word counts.
- **1. Summary**: passed/failed, average per criterion and per category, latency (average and maximum), answer types.
- **2. All questions**: id, category, score, failed, type, words (⚠ over the limit), reason, time to first content, total.
- **3. Worst 10**: question, full answer and what is wrong.
- **4. Recurring problems**.
- **5. Suggestions for the prompt or the profile (not applied)**: written by the judge model; also includes `<profile>/evals/notes.md` if it exists.
- **6. Transcription variants**: whether the mis-transcribed question was understood, and its score against the original.
- **7. Numbers cited and their source**.

Judge rubric: six criteria scored 0 to 2: `correctness`, `real_cases`, `simplicity`, `focus`, `speakable`, `answers_question`. The judge replies in JSON with `scores`, `failed`, `fail_reason`, `summary`, `problems`, `numbers` (`[{number, source}]`) and `understood_question`.
