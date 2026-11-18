"""Profile loading: documents, context block, ready answers (.md/.docx), vocabulary, replacements."""

from __future__ import annotations

from pathlib import Path

from conftest import EXAMPLE_PROFILE
from interview_copilot.evals.runner import parse_cases, projects_text
from interview_copilot.knowledge.loader import Knowledge, approx_tokens, kind_for_folder
from interview_copilot.knowledge.ready_answers import (
    ReadyAnswer,
    build_catalog,
    clean_paragraph,
    load_ready_answers,
    parse_docx,
    parse_markdown,
)
from interview_copilot.knowledge.vocabulary import apply_replacements, load_vocabulary


# ---- loader ----------------------------------------------------------------------------------
def test_kind_for_folder():
    assert kind_for_folder("03-projects") == "projects"
    assert kind_for_folder("07_official-docs") == "official_docs"
    assert kind_for_folder("notes") is None
    assert kind_for_folder("99-other") is None


def test_loader_folders_kinds_order_and_skips(profile: Path):
    (profile / "04-skills" / "evals").mkdir()
    (profile / "04-skills" / "evals" / "x.md").write_text("EVAL", encoding="utf-8")
    k = Knowledge.load(profile)
    paths = [d.path.as_posix() for d in k.documents]
    assert paths == sorted(paths, key=lambda p: (p.split("/")[0], p))
    assert paths == [
        "01-instructions/instructions.md",
        "02-resume/resume.md",
        "03-projects/projects.md",
        "04-skills/python.md",
        "04-skills/sub/go.md",
        "05-ready-answers/ready-answers.md",
        "06-job/job.md",
        "07-official-docs/01 - asyncio.md",
    ]
    kinds = {d.path.as_posix(): d.kind for d in k.documents}
    assert kinds["04-skills/sub/go.md"] == "skills"
    assert kinds["07-official-docs/01 - asyncio.md"] == "official_docs"
    block = k.context_block()
    for skipped in ("DRAFT", "HIDDEN", "LOCK", "NOT NUMBERED", "EVAL", "PNG", "https://docs.python.org/3/library"):
        assert skipped not in block


def test_profile_metadata(profile: Path):
    k = Knowledge.load(profile)
    assert k.profile.name == "Sam Lee"
    assert k.profile.target_role == "Backend Engineer"
    assert k.profile.native_language == "Spanish"
    assert k.research_domains == ["docs.python.org"]
    assert k.replacements == {"pie test": "pytest"}
    assert k.ready_answers_file == profile / "05-ready-answers" / "ready-answers.md"


def test_context_block_sections(profile: Path):
    k = Knowledge.load(profile)
    block = k.context_block()
    order = ["<instructions>", "<resume>", "<projects>", "<skills>", "<job>", "<ready_answers_source>",
             "<official_docs>"]
    positions = [block.index(tag) for tag in order]
    assert positions == sorted(positions)
    for tag in order:
        assert f"</{tag[1:]}" in block
    assert '<doc name="04-skills/sub/go.md">\n# Go\nGoroutines.\n</doc>' in block
    assert k.approx_tokens() == approx_tokens(block + "\n" + k.catalog())
    assert approx_tokens("x" * 32) == 10
    assert "8 files" not in k.summary() and "1 official docs" in k.summary()


def test_missing_sections_are_omitted(tmp_path: Path):
    (tmp_path / "02-resume").mkdir()
    (tmp_path / "02-resume" / "cv.txt").write_bytes("Café résumé".encode("cp1252"))
    k = Knowledge.load(tmp_path)
    assert k.context_block() == '<resume>\n<doc name="02-resume/cv.txt">\nCafé résumé\n</doc>\n</resume>'
    assert k.profile.name == "the candidate"
    assert k.ready_answers == {}


def test_missing_profile_folder(tmp_path: Path):
    k = Knowledge.load(tmp_path / "nope")
    assert k.documents == [] and k.context_block() == ""


def test_docx_document_is_read(tmp_path: Path):
    import docx

    d = docx.Document()
    d.add_paragraph("Notes about the job")
    t = d.add_table(rows=1, cols=2)
    t.rows[0].cells[0].text = "Stack"
    t.rows[0].cells[1].text = "Python"
    (tmp_path / "06-job").mkdir()
    d.save(tmp_path / "06-job" / "job.docx")
    k = Knowledge.load(tmp_path)
    assert k.documents[0].kind == "job"
    assert "Notes about the job" in k.context_block() and "Stack | Python" in k.context_block()


def test_example_profile_loads():
    k = Knowledge.load(EXAMPLE_PROFILE)
    assert k.profile.name == "Alex Morgan"
    assert len(k.ready_answers) == 22
    assert list(k.ready_answers)[:3] == ["1", "2", "3"]
    assert k.ready_answers["1"].title == "Tell me about yourself"
    assert all(kind in {d.kind for d in k.documents}
               for kind in ("instructions", "resume", "projects", "skills", "ready_answers", "job"))
    assert k.vocabulary and "FastAPI" in k.vocabulary
    assert k.replacements["fast API"] == "FastAPI"
    cases = parse_cases(projects_text(k))
    assert [c.name for c in cases] == ["Shipment events pipeline", "Tracking API latency",
                                       "Appointment report query", "Duplicate reminder incident",
                                       "CI pipeline speed-up", "Nightly sales ETL"]
    assert all(c.keywords for c in cases)
    assert k.approx_tokens() < 100_000


# ---- ready answers ---------------------------------------------------------------------------
def test_clean_paragraph():
    assert clean_paragraph("Tip: say it slowly") == ""
    assert clean_paragraph("note: internal") == ""
    assert clean_paragraph("If asked about money, deflect") == ""
    assert clean_paragraph("Rules: short") == ""
    assert clean_paragraph('With the manager: "As we agreed."') == '"As we agreed."'
    assert clean_paragraph("With the recruiter: “Sure.”") == "“Sure.”"
    assert clean_paragraph("  Plain answer.  ") == "Plain answer."


def test_parse_markdown(profile: Path):
    path = profile / "05-ready-answers" / "ready-answers.md"
    answers = parse_markdown(path, exclude=["Internal notes"])
    assert [(a.id, a.title) for a in answers] == [("1", "Tell me about yourself"),
                                                  ("2", "Why are you leaving?")]
    assert answers[0].text == "I'm Sam. I have six years of Go and Python."   # Tip line dropped
    assert answers[1].text.endswith("## not a heading inside a fence")   # a fence is text, not a heading
    assert len(parse_markdown(path)) == 3
    assert load_ready_answers(path, ["internal notes"]) == answers           # case-insensitive exclude


def test_parse_markdown_levels(tmp_path: Path):
    f = tmp_path / "ra.md"
    f.write_text("# Title\nintro\n### Deep one\nAnswer A.\n#### too deep\nstill A.\n"
                 "## Empty\n\n## B\nAnswer B.\n", encoding="utf-8")
    answers = parse_markdown(f)
    assert [(a.id, a.title, a.text) for a in answers] == [("1", "Deep one", "Answer A."),
                                                          ("2", "B", "Answer B.")]


def _training_docx(path: Path) -> None:
    import docx

    d = docx.Document()
    d.add_heading("Interview training", level=1)
    d.add_paragraph("Role: backend engineer.")
    d.add_heading("1. Introduction pitch", level=2)
    d.add_paragraph("Rules: short and honest.")
    d.add_paragraph("“I'm Sam. I have six years in tech.”")
    d.add_heading("3b. Salary expectation", level=2)
    d.add_paragraph("With the recruiter: “Within the budgeted range.”")
    d.add_paragraph("If the client asks: “As agreed with the agency.”")
    d.add_heading("3m. A real queue case", level=2)
    d.add_paragraph("“At Acme, I moved orders to a queue.”")
    d.add_paragraph("Tip: this is your best example.")
    d.add_heading("5. Technical notes", level=2)
    d.add_paragraph("Not an answer.")
    d.add_heading("7. Architecture round", level=2)
    d.add_heading("Scenario 1: an order must reach the ERP", level=3)
    d.add_paragraph("“I would publish an event.”")
    d.add_paragraph("Tip: mention retries.")
    d.add_heading("Scenario 2: one line failed", level=3)
    d.add_paragraph("It depends on the business rule.")
    d.add_heading("Unnumbered section", level=2)
    d.add_paragraph("“Ignored.”")
    d.save(path)


def test_parse_docx(tmp_path: Path):
    f = tmp_path / "training.docx"
    _training_docx(f)
    answers = parse_docx(f, exclude=["5"])
    assert [a.id for a in answers] == ["1", "3b", "3m", "7.1", "7.2"]
    by = {a.id: a for a in answers}
    assert by["1"].text == "“I'm Sam. I have six years in tech.”"
    assert by["3b"].text.count("“") == 2 and "recruiter" not in by["3b"].text
    assert "Tip" not in by["3m"].text and "Tip" not in by["7.1"].text
    assert by["7.1"].title == "7. Scenario 1: an order must reach the ERP"
    assert by["7.2"].text == "It depends on the business rule."   # no quotes -> every paragraph
    assert load_ready_answers(f, ["5"]) == answers
    assert "5" in [a.id for a in parse_docx(f)]


def test_docx_ready_answers_in_profile(tmp_path: Path):
    folder = tmp_path / "05-ready-answers"
    folder.mkdir()
    _training_docx(folder / "training.docx")
    (tmp_path / "profile.toml").write_text('[ready_answers]\nfile = "05-ready-answers/training.docx"\n'
                                           'exclude_headings = ["5"]\n', encoding="utf-8")
    k = Knowledge.load(tmp_path)
    assert list(k.ready_answers) == ["1", "3b", "3m", "7.1", "7.2"]
    assert "3m | 3m. A real queue case" in k.catalog()


def test_load_ready_answers_edge_cases(tmp_path: Path):
    assert load_ready_answers(None) == []
    assert load_ready_answers(tmp_path / "missing.md") == []
    (tmp_path / "x.pdf").write_text("x")
    assert load_ready_answers(tmp_path / "x.pdf") == []


def test_build_catalog():
    cat = build_catalog([ReadyAnswer("1", "Pitch", "..."), ReadyAnswer("3c", "3c. Queue", "...")])
    assert cat == "<ready_answer_catalog>\n1 | Pitch\n3c | 3c. Queue\n</ready_answer_catalog>"
    assert build_catalog([]) == "<ready_answer_catalog>\n</ready_answer_catalog>"
    assert ReadyAnswer("1", "Pitch", "x").label == "Pitch"


# ---- vocabulary ------------------------------------------------------------------------------
def test_vocabulary(profile: Path):
    assert load_vocabulary(profile / "vocabulary.txt") == ["Sam Lee", "C#", "RabbitMQ"]
    assert load_vocabulary(profile / "missing.txt") == []


def test_replacements():
    rep = {"pie test": "pytest", "fast API": "FastAPI", "C sharp": "C#"}
    assert apply_replacements("We use Pie Test and fast-api daily", rep) == "We use pytest and FastAPI daily"
    assert apply_replacements("fast APIs", rep) == "fast APIs"                 # whole phrase only
    assert apply_replacements("I know c sharp.", rep) == "I know C#."
    assert apply_replacements("", rep) == ""
    assert apply_replacements("unchanged", {}) == "unchanged"
    assert apply_replacements("a.b", {"a.b": "x", " ": "y"}) == "x"           # regex-safe, blank keys ignored
