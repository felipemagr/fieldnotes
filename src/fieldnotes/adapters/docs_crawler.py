"""Crawl a docs site into one markdown file the Brain reads once per call.

Same-domain pages only, robots.txt respected, a polite delay between requests and a page limit.
Every heading with an anchor keeps a `[ref: url#anchor]` tag so the Brain can cite the section.
"""

import logging
import re
import time
from collections import deque
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify
from pydantic import BaseModel

from fieldnotes.adapters.cache import JsonCache

logger = logging.getLogger(__name__)

USER_AGENT = "fieldnotes-docs-crawler/0.1 (+local, personal use)"
SKIP_EXTENSIONS = re.compile(
    r"\.(png|jpe?g|gif|svg|ico|css|js|json|pdf|zip|woff2?|ttf|mp4|webp)$", re.IGNORECASE
)
DROP_TAGS = [
    "script",
    "style",
    "noscript",
    "svg",
    "nav",
    "header",
    "footer",
    "aside",
    "button",
    "input",
    "form",
    "iframe",
    "img",
]


class Page(BaseModel):
    url: str
    title: str
    markdown: str
    links: list[str] = []
    etag: str | None = None
    last_modified: str | None = None


REF = re.compile(r"\[ref: ([^\]]+)\]")


def sections(markdown: str) -> dict[str, str]:
    """Each anchored section's text, keyed by its `[ref: url#id]`."""
    found: dict[str, str] = {}
    ref = None
    for line in markdown.splitlines():
        if line.startswith("#") and (m := REF.search(line)):
            ref = m.group(1)
            found[ref] = ""
        elif ref:
            found[ref] += line + "\n"
    return found


class Changes(BaseModel):
    added: list[str] = []
    removed: list[str] = []
    changed: list[str] = []

    def __bool__(self) -> bool:
        return bool(self.added or self.removed or self.changed)

    def __str__(self) -> str:
        parts = [
            f"{sign}{len(refs)} {label}: " + ", ".join(r.split("#")[-1] for r in refs)
            for sign, label, refs in (
                ("+", "added", self.added),
                ("-", "removed", self.removed),
                ("~", "changed", self.changed),
            )
            if refs
        ]
        return "; ".join(parts) or "no changes"


class DocsBundle(BaseModel):
    start_url: str
    pages: list[Page]

    def changes_since(self, old: "DocsBundle") -> Changes:
        new_s, old_s = sections(self.markdown), sections(old.markdown)
        return Changes(
            added=[r for r in new_s if r not in old_s],
            removed=[r for r in old_s if r not in new_s],
            changed=[r for r in new_s if r in old_s and new_s[r] != old_s[r]],
        )

    @property
    def markdown(self) -> str:
        return "\n\n".join(
            f"# Page: {p.title}\nSource: {p.url}\n\n{p.markdown}" for p in self.pages
        )

    @property
    def approx_tokens(self) -> int:
        return len(self.markdown) // 4


def same_site(url: str, start: str) -> bool:
    return urlparse(url).netloc == urlparse(start).netloc


def html_to_markdown(html: str, url: str) -> tuple[str, str]:
    """(title, markdown) of one page, anchors kept as `[ref: url#id]` on headings."""
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.title.string or "").strip() if soup.title else url
    for tag in soup(DROP_TAGS):
        tag.decompose()
    base = urldefrag(url)[0]
    for el in soup.find_all(id=True):
        heading = el if re.fullmatch(r"h[1-6]", el.name or "") else el.find(re.compile("^h[1-6]$"))
        if heading is None or heading.get("data-ref"):
            continue
        heading["data-ref"] = "1"
        heading.append(f" [ref: {base}#{el['id']}]")
    root = soup.find("main") or soup.body or soup
    md = markdownify(str(root), heading_style="ATX", bullets="-")
    md = re.sub(r"\n{3,}", "\n\n", md)
    md = "\n".join(line.rstrip() for line in md.splitlines()).strip()
    return title, md


def links(html: str, url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    found = []
    for a in soup.find_all("a", href=True):
        target = urldefrag(urljoin(url, a["href"]))[0]
        if target.startswith("http") and not SKIP_EXTENSIONS.search(urlparse(target).path):
            found.append(target)
    return found


def load_robots(client: httpx.Client, start: str) -> RobotFileParser:
    robots = RobotFileParser()
    parts = urlparse(start)
    try:
        response = client.get(f"{parts.scheme}://{parts.netloc}/robots.txt")
        is_robots = response.status_code == 200 and "html" not in response.headers.get(
            "content-type", ""
        )
        robots.parse(response.text.splitlines() if is_robots else [])
    except httpx.HTTPError:
        robots.parse([])
    return robots


def crawl(
    start_url: str,
    max_pages: int = 40,
    delay_s: float = 0.5,
    client: httpx.Client | None = None,
    max_seconds: float = 60.0,
    previous: DocsBundle | None = None,
) -> DocsBundle:
    """Stops at `max_pages` or after `max_seconds`, keeping what it fetched so far.

    With `previous`, each known page is asked for only if it changed (ETag / Last-Modified):
    an unchanged page costs one small request that comes back 304 with no body.
    """
    known = {p.url: p for p in previous.pages} if previous else {}
    deadline = time.monotonic() + max_seconds
    client = client or httpx.Client(
        headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=10
    )
    robots = load_robots(client, start_url)
    start = urldefrag(start_url)[0]
    queue, seen, pages, bodies = deque([start]), {start}, [], set()
    while queue and len(pages) < max_pages:
        if time.monotonic() > deadline:
            logger.warning("Crawl stopped after %.0fs with %d page(s)", max_seconds, len(pages))
            break
        url = queue.popleft()
        if not robots.can_fetch(USER_AGENT, url):
            logger.info("robots.txt disallows %s", url)
            continue
        if pages:
            time.sleep(delay_s)
        old = known.get(url)
        headers = {}
        if old and old.etag:
            headers["If-None-Match"] = old.etag
        if old and old.last_modified:
            headers["If-Modified-Since"] = old.last_modified
        try:
            response = client.get(url, headers=headers)
        except httpx.HTTPError as e:
            logger.warning("Could not fetch %s: %s", url, e)
            continue
        if response.status_code == 304 and old:
            page = old
        elif response.status_code == 200 and "html" in response.headers.get("content-type", ""):
            title, md = html_to_markdown(response.text, url)
            page = Page(
                url=url,
                title=title,
                markdown=md,
                links=links(response.text, url),
                etag=response.headers.get("etag"),
                last_modified=response.headers.get("last-modified"),
            )
            logger.info("Fetched %s (%d chars)", url, len(md))
        else:
            continue
        # The same page under two URLs (`/` and `/index.html`) is kept once.
        body = REF.sub("", page.markdown)
        if body in bodies:
            continue
        bodies.add(body)
        pages.append(page)
        for link in page.links:
            if link not in seen and same_site(link, start):
                seen.add(link)
                queue.append(link)
    return DocsBundle(start_url=start_url, pages=pages)


class DocsLibrary:
    """The last crawl of each docs site, on disk."""

    def __init__(self, directory: Path):
        self.cache = JsonCache(directory)

    def get(self, url: str) -> DocsBundle | None:
        payload = self.cache.get(url)
        return DocsBundle.model_validate(payload) if payload else None

    def put(self, bundle: DocsBundle) -> Path:
        path = self.cache.put(bundle.start_url, bundle.model_dump())
        md_path = path.with_suffix(".md")
        md_path.write_text(bundle.markdown, encoding="utf-8")
        return md_path
