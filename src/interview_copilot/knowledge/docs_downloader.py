"""Downloads official documentation pages into the profile's ``07-official-docs/`` folder.

Reads ``07-official-docs/links.txt`` (one URL per line, ``#`` comments allowed), downloads each
page, converts the article body to Markdown (no menus or footers) and saves it as
``NN - <title>.md`` with its source URL on top. Microsoft Learn training modules
(``/training/modules/...``) are expanded: their units come from the Learn hierarchy API and are
joined into one document (knowledge checks skipped).
"""

from __future__ import annotations

import datetime as dt
import json
import re
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) InterviewCopilot/2.0"
URL_RE = re.compile(r"https?://[^\s)>\]]+")
DOCS_FOLDER = "07-official-docs"
LEARN_HOST = "https://learn.microsoft.com"
SKIP_CLASSES = ("feedback", "page-metadata", "contributors", "action-container",
                "display-none", "visually-hidden", "is-hidden", "sr-only")
TRAILING_SECTIONS = re.compile(r"\n#+ (Feedback|Additional resources|In this article)\s*\n")


def read_links(path: str | Path) -> list[str]:
    """Unique URLs from a links file (one per line; ``#`` lines are comments)."""
    p = Path(path)
    if not p.is_file():
        return []
    links: list[str] = []
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for url in URL_RE.findall(line):
            url = url.rstrip(".,;:'\"")
            if url not in links:
                links.append(url)
    return links


# ---------------------------------------------------------------------------------------------
# HTML -> Markdown (article only)
# ---------------------------------------------------------------------------------------------
def _text(el) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()


def _inline(el) -> str:
    from bs4 import NavigableString, Tag

    out: list[str] = []
    for c in el.children:
        if isinstance(c, NavigableString):
            out.append(str(c))
        elif isinstance(c, Tag):
            if c.name == "code":
                out.append(f"`{c.get_text()}`")
            elif c.name in ("strong", "b"):
                out.append(f"**{_inline(c).strip()}**")
            elif c.name == "br":
                out.append("\n")
            elif c.name in ("script", "style"):
                continue
            else:
                out.append(_inline(c))
    return re.sub(r"[ \t\r\f\v]+", " ", "".join(out))


def _table(el) -> list[str]:
    rows = []
    for tr in el.find_all("tr"):
        cells = [_text(td).replace("|", "\\|") for td in tr.find_all(["th", "td"])]
        if cells:
            rows.append(cells)
    if not rows:
        return []
    n = max(len(r) for r in rows)
    rows = [r + [""] * (n - len(r)) for r in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * n]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return lines + [""]


def _block(el, out: list[str], depth: int = 0) -> None:
    from bs4 import NavigableString, Tag

    for c in el.children:
        if isinstance(c, NavigableString):
            t = str(c).strip()
            if t:
                out.append(t)
            continue
        if not isinstance(c, Tag):
            continue
        cls = " ".join(c.get("class", []))
        if (c.name in ("script", "style", "nav", "button", "form", "svg", "header", "footer")
                or any(k in cls for k in SKIP_CLASSES) or c.get("hidden") is not None):
            continue
        if re.fullmatch(r"h[1-6]", c.name):
            out += ["", "#" * int(c.name[1]) + " " + _text(c), ""]
        elif c.name == "p":
            t = _inline(c).strip()
            if t:
                out += [t, ""]
        elif c.name in ("ul", "ol"):
            _block_list(c, out, depth)
            out.append("")
        elif c.name == "table":
            out += _table(c)
        elif c.name == "pre":
            out += ["```", c.get_text().rstrip(), "```", ""]
        elif c.name == "div" and "alert" in cls:
            t = _text(c)
            if t:
                out += ["> " + t, ""]
        else:
            _block(c, out, depth)


def _block_list(lst, out: list[str], depth: int) -> None:
    from bs4 import Tag

    for i, li in enumerate(lst.find_all("li", recursive=False), 1):
        bullet = f"{i}." if lst.name == "ol" else "-"
        parts = [p for p in li.children if not (isinstance(p, Tag) and p.name in ("ul", "ol"))]
        raw = "".join(p if isinstance(p, str) else p.get_text(" ") for p in parts)
        txt = re.sub(r"\s+", " ", raw).strip()
        out.append("  " * depth + f"{bullet} {txt}")
        for sub in li.find_all(["ul", "ol"], recursive=False):
            _block_list(sub, out, depth + 1)


def html_to_markdown(html: str) -> tuple[str, str]:
    """Convert a documentation page to ``(title, markdown of the article body)``."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.select_one("main h1") or soup.find("h1")
    if h1:
        title = _text(h1)
    elif soup.title and soup.title.string:
        title = soup.title.string.split(" - ")[0].split(" | ")[0].strip()
    else:
        title = "Document"
    main = soup.find("main") or soup.find("article") or soup.body or soup
    # Microsoft Learn keeps the article in the largest div.content inside <main>
    candidates = main.select("div.content") or main.select("article") or [main]
    article = max(candidates, key=lambda d: len(d.get_text()))
    out: list[str] = []
    _block(article, out)
    md = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()
    md = TRAILING_SECTIONS.split(md)[0]
    return title, md


def slugify(title: str) -> str:
    """File-name-safe version of a title (max 80 characters)."""
    s = re.sub(r"[^\w\s-]", "", title, flags=re.UNICODE).strip()
    return re.sub(r"[\s_]+", "-", s)[:80] or "document"


def fetch(url: str, timeout: int = 30) -> str:
    """GET a URL and return the body as text."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def fetch_page(url: str, fetcher: Callable[[str], str] = fetch, pause_s: float = 0.3) -> tuple[str, str]:
    """Download one page and return ``(title, markdown)``.

    Microsoft Learn training modules have their content split into units: the unit list comes
    from the Learn hierarchy API and every unit (except the knowledge check) is appended.
    """
    html = fetcher(url)
    title, md = html_to_markdown(html)
    if "/training/modules/" not in url:
        return title, md
    m = re.search(r'<meta name="uid" content="([^"]+)"', html)
    if not m:
        return title, md
    api = f"{LEARN_HOST}/api/hierarchy/modules/{m.group(1)}?locale=en-us"
    units = json.loads(fetcher(api)).get("units", [])
    parts = [md]
    for unit in units:
        unit_url = unit.get("url") or ""
        slug = re.sub(r"^\d+-", "", unit_url.rstrip("/").rsplit("/", 1)[-1])   # "5-knowledge-check"
        if not unit_url or slug in ("check", "knowledge-check"):
            continue
        u_title, u_md = html_to_markdown(fetcher(LEARN_HOST + unit_url))
        parts.append(f"## Unit: {unit.get('title') or u_title}\n\n{u_md}")
        if pause_s:
            time.sleep(pause_s)
    return title, "\n\n".join(parts)


def download_docs(profile_path: str | Path, out: Callable[[str], None] = print,
                  fetcher: Callable[[str], str] = fetch, pause_s: float = 0.5) -> int:
    """Download every URL of ``07-official-docs/links.txt``. Returns how many pages were saved."""
    folder = Path(profile_path) / DOCS_FOLDER
    links_file = folder / "links.txt"
    links = read_links(links_file)
    if not links:
        out(f"No URLs found in {links_file}")
        return 0
    folder.mkdir(parents=True, exist_ok=True)
    out(f"{len(links)} links in {links_file.name}. Saving to {folder}\n")
    today = dt.date.today().isoformat()
    saved = 0
    for i, url in enumerate(links, 1):
        try:
            title, md = fetch_page(url, fetcher, pause_s=pause_s)
            if len(md) < 200:
                raise RuntimeError("no recognizable article content")
            name = f"{i:02d} - {slugify(title)}.md"
            for old in folder.glob(f"{i:02d} - *.md"):   # the title may have changed
                if old.name != name:
                    old.unlink()
            (folder / name).write_text(
                f"# {title}\n\nSource: {url}\nDownloaded: {today}\n\n{md}\n", encoding="utf-8")
            saved += 1
            out(f"  OK    {name}  ({len(md):,} characters)")
        except Exception as e:  # noqa: BLE001 - report and continue with the next link
            out(f"  ERROR {url}\n        {e}")
        if pause_s:
            time.sleep(pause_s)
    out(f"\n{saved}/{len(links)} pages saved.")
    return saved
