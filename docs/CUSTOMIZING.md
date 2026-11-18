# Customizing: build your own profile

The copilot is only as good as the files you give it. This guide shows how to create a profile, what to write in each folder, and how to refine it with evals.

## 1. Create the profile

```powershell
Copy-Item -Recurse profiles\_template profiles\me
```

Then make it the active profile, either per command:

```powershell
python -m interview_copilot check --profile profiles\me
```

or permanently in `config\settings.local.toml` (gitignored):

```toml
[profile]
path = "profiles/me"
```

`profiles/me/` is gitignored, so your resume never ends up in a commit. Keep `profiles/example/` open as a reference while you write.

## 2. Fill in `profile.toml`

```toml
[candidate]
name = "Your Name"
target_role = "Senior Data Engineer"
native_language = "Brazilian Portuguese"   # translation and INTENT line are written in this language

[ready_answers]
file = "05-ready-answers/ready-answers.md"  # or a .docx
exclude_headings = []                       # exact heading texts that are not answers

[research]
allowed_domains = ["docs.python.org"]       # domains for the research hotkey (web search)

[transcript_replacements]
# "Jango" = "Django"                        # case-insensitive whole-phrase replacement
```

## 3. Write each folder

Every `.md`, `.txt` and `.docx` file inside `01-` to `07-` is loaded (subfolders included), sorted by path. Files starting with `~$`, `_` or `.` are skipped, so you can keep drafts as `_draft.md`.

### `01-instructions/instructions.md`: how the copilot behaves for you

- The role and the focus of this interview (for example, "system design round, 45 minutes").
- Rules specific to you: topics to steer toward, things never to claim, tone.
- Keep it short and imperative. Generic rules (honesty, length, format) are already in the system prompt; do not repeat them.

### `02-resume/resume.md`: who you are

- Summary, stack, experience (company type, role, dates, main results), education, certifications.
- Write facts, not adjectives. Numbers here are the **only** numbers the copilot may say about you.
- Plain markdown headings and bullets work best.

### `03-projects/projects.md`: your real cases and the topic map

- One section per case. Context, what you did, the result. The copilot uses cases **exactly as written** and never adds reasons, timelines or lessons, so write what you would actually say.
- Add a **`Topic → case` table**. It tells the model which single case to use for each kind of question, and the evals use the case names from it to detect answers that mix cases.

```markdown
## Topic → case

| Topic | Case |
|---|---|
| Performance, scaling, caching | Order API latency |
| Data migration, legacy systems | Billing database migration |
| Conflict, disagreement with a stakeholder | Release freeze negotiation |
```

### `04-skills/`: technical knowledge

- One file per skill, language or platform: `python.md`, `fastapi.md`, `sql.md`, `aws.md`.
- Write the concepts you want to explain in your own words, the trade-offs you know, and the "simplest solution first" version of common answers.
- Mark what you have used in production versus what you only studied. The copilot uses this to stay honest.

### `05-ready-answers/ready-answers.md`: prepared answers

Format:

```markdown
# Ready answers

## Tell me about yourself
I'm Alex. I have eight years of experience building Python backends...
Tip: keep it under 40 seconds.

## Why are you leaving your current job?
...
```

- Every `##` or `###` heading is one answer; IDs are assigned in order (`1`, `2`, `3`…). In a `.docx`, use the Heading 2 / Heading 3 styles.
- The paragraphs under the heading are shown **verbatim**. Lines starting with `Tip:`, `Note:` or `If asked` are coaching for you and are never shown. A label before a quote (`Project: "…"`) is stripped.
- **Write the heading as the question an interviewer would ask.** The "same subject?" check compares the question with the heading, so `## Why are you leaving your current job?` matches better than `## Exit story`.
- **Length**: aim for 60 to 120 words (20 to 45 seconds spoken). The pitch ("Tell me about yourself") can be a little longer. Short sentences you can read aloud without stumbling.
- One question per heading. If two questions need different answers ("Why this company?" and "Why this role?"), make two headings.
- Use `exclude_headings` for sections that are notes, not answers.

### `06-job/job.md`: the target job

The job description, what you know about the company and the interviewers, and the questions you want to ask at the end.

### `07-official-docs/`: reference documentation

Put one URL per line in `links.txt` (`#` starts a comment), then:

```powershell
python -m interview_copilot download-docs
```

Each page is saved as `.md` next to `links.txt` (only the article, without menus; Microsoft Learn training modules are downloaded with all their units; other sites go through a generic HTML-to-markdown conversion). Official docs outrank the model's general knowledge, and a ready answer that conflicts with them gets a `DOCS:` warning.

Watch the size: `check` prints the token count, and anything above `[knowledge] warn_tokens` (100,000) is flagged. Prefer a few focused pages over whole manuals.

## 4. Vocabulary and transcript replacements

**`vocabulary.txt`**: names and terms speech recognition must get right, one per line (`#` for comments): your name, company types, frameworks, acronyms.

```text
# people and products
Alex Morgan
FastAPI
PostgreSQL
Kubernetes
```

- With Deepgram `nova-3`, the terms are sent as keyterms (up to 100). With Whisper, they become the initial prompt.
- The same list is given to the model, which fixes obvious misspellings.
- Keep it focused on words that are actually misheard; 100 is the limit.

**`[transcript_replacements]`** in `profile.toml`: deterministic fixes applied to every transcribed question before anything else. Use it for recurring mistakes you saw in practice:

```toml
[transcript_replacements]
"fast API" = "FastAPI"
"post grass" = "Postgres"
```

## 5. Settings you will tune

Put overrides in `config/settings.local.toml`; only the keys you change.

| Setting | Default | When to change |
|---|---|---|
| `[stt] pause_ms` | `700` | Questions cut in the middle → 900–1000. Want more speed and the interviewer speaks fluently → 500–600 |
| `[ai] answer_words_target` / `answer_words_max` | `70` / `80` | Longer or shorter generated answers. Ready answers are not affected |
| `[ai] effort` | `"low"` | `"medium"` for more careful answers, at the cost of latency |
| `[ai] model` | `claude-haiku-5-5` | The fastest model; change only if you accept slower answers |
| `[research] model` | `claude-sonnet-5-5` | Model for the on-demand research hotkey |
| `[ai] min_words_auto` | `4` | Utterances shorter than this do not trigger an answer |
| `[ai] auto_suggest` | `true` | `false`: answers only on `Ctrl+Alt+S` (translation stays automatic) |
| `[ai] history_turns` | `3` | How many previous questions are sent for follow-ups |
| `[ai] check_ready_answers` | `true` | Turn off the "same subject?" check (faster, less safe) |
| `[ai] cache_ttl` | `"1h"` | `"5m"` if the 1 h TTL is rejected |
| `[audio] device_name` | `""` | Part of the device name from `devices`, if the default output is not the call |
| `[ui] answer_font_size` | `15` | Readability vs. how much fits without scrolling |

## 6. Refine iteratively with evals

Write `evals/questions.json` with the questions you expect (format in [TESTING.md](TESTING.md#evals)). Include required facts (`must_contain`), things that must never appear (`must_not_contain`), and mis-transcribed variants of important questions (`equivalent_to`).

The loop:

1. **Run** a baseline round:
   ```powershell
   python -m interview_copilot eval --round v1
   ```
2. **Read the report** in `logs/evals/report_v1.md`: start with the summary, then the worst 10 and the recurring problems.
3. **Adjust the files**, not the prompt:
   - wrong ready answer picked → rewrite the heading as the real question, split mixed headings;
   - two cases in one answer → fix the `Topic → case` table;
   - invented or vague facts → add the fact to `resume.md` or `projects.md`, or a rule to `instructions.md`;
   - misheard names in variants → `vocabulary.txt` or `[transcript_replacements]`;
   - answers too long → shorten ready answers or lower `answer_words_target`.
4. **Rerun and compare**:
   ```powershell
   python -m interview_copilot eval --round v2 --compare-with results_v1.json
   ```
   The comparison section shows what improved and what got worse.
5. Iterate on a subset while you work on specific questions (`--ids 3,7,12`), and use `--rejudge` to re-score saved answers after changing `facts` or `auto_fail` without paying for new answers.

Finish with a real practice session: play a mock interview video, run the app, and read `logs/answer_selection.jsonl` to see which ready answers were chosen or rejected.
