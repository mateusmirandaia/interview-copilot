# Profiles

A **profile** is a folder with everything the copilot knows about one candidate and one
interview: who you are, your real cases, your technical notes, your prepared answers and the
job you are applying for. The copilot answers **only** from these files, so the quality of the
answers depends directly on the quality of this content.

```
profiles/
├── README.md      # this file
├── _template/     # empty skeleton: copy it to start your own profile
├── example/       # complete fictional profile (Alex Morgan, Senior Python Backend Engineer)
└── me/            # your profile (create it; gitignored, never committed)
```

The active profile is `[profile] path` in `config/settings.toml` (default `profiles/example`).
You can also pass `--profile profiles/me` to any command.

## Create your own profile

```powershell
Copy-Item -Recurse profiles\_template profiles\me
```

Then, in `config/settings.local.toml` (also gitignored):

```toml
[profile]
path = "profiles/me"
```

Everything under `profiles/` except `README.md`, `_template/` and `example/` is gitignored,
so your resume and answers stay on your machine. Fill the files in the order below, then run
`python -m interview_copilot check` to validate the profile and see the token count.

## Folder by folder

| Path | What goes in it | Why |
|---|---|---|
| `profile.toml` | Name, target role, native language, ready-answers file, research domains, transcript replacements | Metadata and per-profile options. Must be valid TOML. |
| `01-instructions/instructions.md` | How the copilot must behave for you and this interview: focus, do/don't rules, words speech recognition gets wrong | Read first. Your rules win over generic behavior. |
| `02-resume/resume.md` | Summary, stack (with honest levels), experience with dates, education, certifications, **what you do NOT do** | The source of facts about you. The "do not do" list stops invented experience. |
| `03-projects/projects.md` | Your real cases + the `Topic → case` map table | The **only** source of stories. One case per answer. |
| `04-skills/*.md` | One study sheet per skill (e.g. `python.md`, `postgresql.md`, `aws.md`) with "Likely interview questions" | Technical knowledge for definition and "how does X work?" questions. |
| `05-ready-answers/ready-answers.md` | Prepared answers (`.md` or `.docx`) | Shown verbatim when the question matches. Fastest and most controlled answers. |
| `06-job/job.md` | Job ad, company notes, interview process, interviewer notes, questions to ask | Tailors examples to their stack; answers "why this company?". |
| `07-official-docs/links.txt` | Official documentation URLs, one per line | `python -m interview_copilot download-docs` saves them as `.md` here. Official docs outrank the model's memory. |
| `vocabulary.txt` | Names, companies and technical terms, one per line | Improves speech recognition (keyterms) and spelling. |
| `evals/questions.json` | Eval questions, facts and auto-fail rules | `python -m interview_copilot eval` measures answer quality for this profile. |

The loader reads `.md`, `.txt` and `.docx` files in the numbered folders (recursively), sorted by
path. It skips `links.txt`, files starting with `_`, `.` or `~$`, and everything under `evals/`.
HTML comments (`<!-- -->`) in the template are guidance; delete them when you fill a file.

## File formats

### Ready answers (`05-ready-answers/ready-answers.md`)

```markdown
# Ready answers

## Tell me about yourself
I'm Alex Morgan, a backend engineer with 8 years of Python. ...
Tip: keep it under 40 seconds.

## Why are you leaving your current job?
I'm not leaving because of a problem. ...
```

- Every `## ` or `### ` heading is one answer; the heading is the question. IDs are assigned in
  order (`1`, `2`, `3`…).
- The paragraph(s) under the heading are the answer, shown verbatim.
- Lines starting with `Tip:`, `Note:` or `If asked` are coaching for you and are **never shown**.
- Headings that are not answers can be listed in `profile.toml` → `exclude_headings`.
- A `.docx` file also works: Heading 2 / Heading 3 are the questions.

### Projects (`03-projects/projects.md`)

Each case is a `## Case name` section: problem, what you did, technologies, result with real
numbers, and optionally an "EN (spoken)" version. At the top, a map table:

```markdown
## Topic → case map

| Topic | Case |
|---|---|
| Caching, Redis | Tracking API latency |
| Failure, mistake, incident | Duplicate reminder incident |
```

Each topic maps to **exactly one** case. The copilot uses this table to pick the story, and the
evals use the case names to detect answers that mix more than one case.

### Official docs (`07-official-docs/links.txt`)

```text
# Comments start with #
https://docs.python.org/3/library/asyncio.html
```

Keep the list short (5–10 pages on the topics most likely to come up): every downloaded page is
sent with each request. Put the same domains in `profile.toml` → `[research] allowed_domains`.

### Vocabulary (`vocabulary.txt`) and transcript replacements

`vocabulary.txt`: one term per line, `#` comments. Up to 100 terms are sent to speech recognition.
When you see the same transcription mistake in the logs, add it to `profile.toml`:

```toml
[transcript_replacements]
"fast API" = "FastAPI"
```

### Evals (`evals/questions.json`)

`facts` (verified facts the judge enforces), `auto_fail` (extra failure rules) and `questions`
(`id`, `category`, `question`, `must_contain`, `must_not_contain`, `equivalent_to` for
transcription-error variants). See `example/evals/questions.json` and `docs/TESTING.md`.

## Tips for content that produces good answers

- **Write how you speak.** Short sentences, simple words, first person. You will read the answer
  out loud while someone is listening.
- **Real numbers only.** The copilot never invents numbers, so it can only use the ones you write.
  "p95 went from 900 ms to 120 ms" is gold; "much faster" is weak. Never estimate.
- **One case per topic.** If two cases fit a topic, pick the better one in the map. Mixed stories
  sound rehearsed and are easy to break with a follow-up question.
- **Same facts everywhere.** A number in a ready answer must match `projects.md` and the resume.
- **Say what you have NOT done.** A clear "do not do" list and honesty rules (e.g. "basic usage
  only — say so") make the copilot answer gaps honestly and pivot to what you know.
- **Simplest solution first.** Write technical answers that start with the simple, standard
  approach, then go deeper.
- **Ready answers: 60–80 words** (pitch up to 100). Longer answers are hard to read and say live.
- **Keep it focused.** The whole profile is sent on every request (cached). Check the token count
  with `check`; remove notes that are not useful for this interview.
- **Run the evals** after big changes and read the worst answers: they show which file to fix.

See `example/` for a complete profile that works out of the box.
