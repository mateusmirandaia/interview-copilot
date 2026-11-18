"""Official-docs downloader with a fake fetcher (no network)."""

from __future__ import annotations

import json
from pathlib import Path

from interview_copilot.knowledge.docs_downloader import (
    download_docs,
    fetch_page,
    html_to_markdown,
    read_links,
    slugify,
)
from interview_copilot.knowledge.loader import Knowledge

FILLER = "<p>" + "This paragraph has enough words to count as real article content. " * 5 + "</p>"

PAGE = """<html><head><title>Asyncio - Python docs</title></head><body><nav>menu</nav><main id="main">
  <div class="content"><h1>asyncio overview</h1></div>
  <div class="content">
    <div class="alert is-primary"><p>Important</p><p>Requires 3.11.</p></div>
    <h2>Event loop</h2><p>The loop is <strong>single-threaded</strong> and runs <code>Task</code> objects.</p>
    <ul><li>One<ul><li>Sub</li></ul></li><li>Two</li></ul>
    <ol><li>First</li></ol>
    <table><tr><th>Setting</th><th>Default</th></tr><tr><td>debug</td><td>False</td></tr></table>
    <pre><code>asyncio.run(main())</code></pre>
    """ + FILLER + """
    <h2>Feedback</h2><p>Was this page helpful?</p>
  </div></main><footer>footer text</footer></body></html>"""


def test_read_links(tmp_path: Path):
    f = tmp_path / "links.txt"
    f.write_text("# comment https://ignored.example\n\nhttps://a.example/x\n"
                 "- Docs (https://b.example/y).\nhttps://a.example/x\n", encoding="utf-8")
    assert read_links(f) == ["https://a.example/x", "https://b.example/y"]
    assert read_links(tmp_path / "missing.txt") == []


def test_html_to_markdown():
    title, md = html_to_markdown(PAGE)
    assert title == "asyncio overview"
    assert "> Important Requires 3.11." in md
    assert "## Event loop" in md and "**single-threaded**" in md and "`Task`" in md
    assert "- One" in md and "  - Sub" in md and "- Two" in md and "1. First" in md
    assert "| Setting | Default |" in md and "| debug | False |" in md
    assert "```\nasyncio.run(main())\n```" in md
    for absent in ("Feedback", "helpful", "menu", "footer text"):
        assert absent not in md


def test_html_title_fallbacks():
    page = "<html><head><title>Page A - Site</title></head><body><p>x</p></body></html>"
    assert html_to_markdown(page)[0] == "Page A"
    assert html_to_markdown("<p>x</p>")[0] == "Document"


def test_slugify():
    assert slugify("What's new in Python 3.13?") == "Whats-new-in-Python-313"
    assert slugify("!!!") == "document"
    assert len(slugify("x" * 200)) == 80


def test_training_module_units():
    module_url = "https://learn.microsoft.com/en-us/training/modules/intro-mod/"
    module_html = PAGE.replace("<head>", '<head><meta name="uid" content="learn.intro-mod">')
    unit_html = "<main><div class='content'><h1>Unit page</h1>{body}</div></main>"
    hierarchy = {"units": [
        {"title": "Introduction", "url": "/en-us/training/modules/intro-mod/1-introduction"},
        {"title": "Queues", "url": "/en-us/training/modules/intro-mod/2-queues"},
        {"title": "Knowledge check", "url": "/en-us/training/modules/intro-mod/3-knowledge-check"},
        {"title": "Summary", "url": ""}]}
    calls: list[str] = []

    def fetcher(url: str) -> str:
        calls.append(url)
        if "/api/hierarchy/modules/learn.intro-mod" in url:
            return json.dumps(hierarchy)
        if url == module_url:
            return module_html
        return unit_html.format(body=f"<p>Body of {url.rsplit('/', 1)[-1]}</p>")

    title, md = fetch_page(module_url, fetcher, pause_s=0)
    assert title == "asyncio overview"
    assert "## Unit: Introduction" in md and "Body of 1-introduction" in md
    assert "## Unit: Queues" in md
    assert "knowledge-check" not in "".join(calls[2:]) and "Knowledge check" not in md
    assert calls[1] == "https://learn.microsoft.com/api/hierarchy/modules/learn.intro-mod?locale=en-us"


def test_download_docs(tmp_path: Path):
    folder = tmp_path / "07-official-docs"
    folder.mkdir()
    (folder / "links.txt").write_text("https://docs.example/ok\nhttps://docs.example/empty\n"
                                      "https://docs.example/broken\n", encoding="utf-8")
    (folder / "01 - old-title.md").write_text("stale", encoding="utf-8")

    def fetcher(url: str) -> str:
        if url.endswith("broken"):
            raise OSError("HTTP 404")
        if url.endswith("empty"):
            return "<main><h1>Empty</h1><p>short</p></main>"
        return PAGE

    lines: list[str] = []
    saved = download_docs(tmp_path, out=lines.append, fetcher=fetcher, pause_s=0)
    assert saved == 1
    files = sorted(p.name for p in folder.glob("*.md"))
    assert files == ["01 - asyncio-overview.md"]                      # the stale title was replaced
    text = (folder / "01 - asyncio-overview.md").read_text(encoding="utf-8")
    assert text.startswith("# asyncio overview\n\nSource: https://docs.example/ok\nDownloaded: ")
    out = "\n".join(lines)
    assert "ERROR https://docs.example/broken" in out and "HTTP 404" in out
    assert "no recognizable article content" in out and "1/3 pages saved." in out
    docs = Knowledge.load(tmp_path).documents_of("official_docs")
    assert [d.path.name for d in docs] == ["01 - asyncio-overview.md"]


def test_download_docs_without_links(tmp_path: Path):
    lines: list[str] = []
    assert download_docs(tmp_path, out=lines.append, fetcher=lambda u: "", pause_s=0) == 0
    assert lines[0].startswith("No URLs found")
