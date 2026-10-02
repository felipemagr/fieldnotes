"""Crawl a docs site into one markdown file the Brain reads once per call.

Same-domain pages only, robots.txt respected, a polite delay between requests and a page limit.
Every heading with an anchor keeps a `[ref: url#anchor]` tag so the Brain can cite the section.
"""

import logging
import re
import time
from collections import deque
from datetime import timedelta
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


class DocsBundle(BaseModel):
    start_url: str
    pages: list[Page]

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
) -> DocsBundle:
    """Stops at `max_pages` or after `max_seconds`, keeping what it fetched so far."""
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
        try:
            response = client.get(url)
        except httpx.HTTPError as e:
            logger.warning("Could not fetch %s: %s", url, e)
            continue
        if response.status_code != 200 or "html" not in response.headers.get("content-type", ""):
            continue
        title, md = html_to_markdown(response.text, url)
        # The same page under two URLs (`/` and `/index.html`) is kept once.
        body = re.sub(r"\[ref: [^\]]*\]", "", md)
        if body in bodies:
            continue
        bodies.add(body)
        pages.append(Page(url=url, title=title, markdown=md))
        logger.info("Fetched %s (%d chars)", url, len(md))
        for link in links(response.text, url):
            if link not in seen and same_site(link, start):
                seen.add(link)
                queue.append(link)
    return DocsBundle(start_url=start_url, pages=pages)


class DocsLibrary:
    """Crawled docs on disk, refreshed after the TTL."""

    def __init__(self, directory: Path, ttl_days: int):
        self.cache = JsonCache(directory, timedelta(days=ttl_days))

    def get(self, url: str) -> DocsBundle | None:
        payload = self.cache.get(url)
        return DocsBundle.model_validate(payload) if payload else None

    def put(self, bundle: DocsBundle) -> Path:
        path = self.cache.put(bundle.start_url, bundle.model_dump())
        md_path = path.with_suffix(".md")
        md_path.write_text(bundle.markdown, encoding="utf-8")
        return md_path
