import httpx

from fieldnotes.adapters.docs_crawler import DocsLibrary, crawl

ROBOTS = "User-agent: *\nDisallow: /private/\n"


def client_for(site, seen=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append((request.url.path, request.headers.get("if-none-match")))
        path = request.url.path
        if request.url.host != "docs.example.com":
            raise AssertionError(f"left the domain: {request.url}")
        if path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS, headers={"content-type": "text/plain"})
        if path.startswith("/private"):
            raise AssertionError("robots.txt was ignored")
        name = "index.html" if path in ("/", "/index.html") else path.lstrip("/")
        file = site / name
        if not file.exists():
            return httpx.Response(404, text="nope", headers={"content-type": "text/html"})
        etag = f'"{hash(file.read_text())}"'
        if request.headers.get("if-none-match") == etag:
            return httpx.Response(304)
        return httpx.Response(
            200, text=file.read_text(), headers={"content-type": "text/html", "etag": etag}
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_crawl_fixture(fixtures, tmp_path):
    bundle = crawl("https://docs.example.com/", delay_s=0, client=client_for(fixtures / "site"))
    urls = [p.url for p in bundle.pages]
    assert urls == ["https://docs.example.com/", "https://docs.example.com/payments.html"]
    md = bundle.markdown
    assert "[ref: https://docs.example.com/#declarations]" in md
    assert "[ref: https://docs.example.com/#dry-run]" in md
    assert "POST /v2/{deal\\_id}/payments/bulk" in md or "POST /v2/{deal_id}/payments/bulk" in md
    assert "var x" not in md  # scripts dropped
    assert "Source: https://docs.example.com/payments.html" in md

    library = DocsLibrary(tmp_path)
    md_path = library.put(bundle)
    assert md_path.read_text() == md
    assert library.get("https://docs.example.com/").pages == bundle.pages


def test_crawl_respects_page_limit(fixtures):
    bundle = crawl(
        "https://docs.example.com/", max_pages=1, delay_s=0, client=client_for(fixtures / "site")
    )
    assert len(bundle.pages) == 1


def test_unchanged_docs_cost_a_304_each(fixtures):
    site = fixtures / "site"
    first = crawl("https://docs.example.com/", delay_s=0, client=client_for(site))
    seen = []
    again = crawl(
        "https://docs.example.com/", delay_s=0, client=client_for(site, seen), previous=first
    )
    stored = {httpx.URL(p.url).path for p in first.pages}
    asked = {path: etag for path, etag in seen if path in stored}
    assert asked.keys() == stored and all(asked.values())  # each stored page: conditional GET
    assert again.pages == first.pages
    assert not again.changes_since(first)


def test_changes_name_the_sections(fixtures, tmp_path):
    import shutil

    site = tmp_path / "site"
    shutil.copytree(fixtures / "site", site)
    first = crawl("https://docs.example.com/", delay_s=0, client=client_for(site))
    index = site / "index.html"
    index.write_text(
        index.read_text()
        .replace("validate only", "validate without saving")
        .replace("</section>", '<h3 id="webhooks">Webhooks</h3><p>New.</p></section>')
    )
    second = crawl("https://docs.example.com/", delay_s=0, client=client_for(site), previous=first)
    changes = second.changes_since(first)
    assert changes.added == ["https://docs.example.com/#webhooks"]
    assert changes.changed == ["https://docs.example.com/#dry-run"]
    assert str(changes) == "+1 added: webhooks; ~1 changed: dry-run"
