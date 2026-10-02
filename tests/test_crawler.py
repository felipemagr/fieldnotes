import httpx

from fieldnotes.adapters.docs_crawler import DocsLibrary, crawl

ROBOTS = "User-agent: *\nDisallow: /private/\n"


def client_for(site):
    def handler(request: httpx.Request) -> httpx.Response:
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
        return httpx.Response(200, text=file.read_text(), headers={"content-type": "text/html"})

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

    library = DocsLibrary(tmp_path, ttl_days=7)
    md_path = library.put(bundle)
    assert md_path.read_text() == md
    assert library.get("https://docs.example.com/").pages == bundle.pages


def test_crawl_respects_page_limit(fixtures):
    bundle = crawl(
        "https://docs.example.com/", max_pages=1, delay_s=0, client=client_for(fixtures / "site")
    )
    assert len(bundle.pages) == 1
