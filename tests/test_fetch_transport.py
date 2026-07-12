"""Focused route and legacy-decoding coverage for the fetching boundary."""

from dataclasses import dataclass, field
from datetime import date
from typing import Final

import pytest
from scraper import fetch_transport
from scraper.fetching import (
    EngineDocument,
    EngineRequest,
    FetchDependencies,
    HttpDocument,
    HttpRequest,
    collect_site,
)

HOME: Final = "https://paper.example/"
ALL_URL: Final = f"{HOME}rss/allArticle.xml"
CLICK_URL: Final = f"{HOME}rss/clickTop.xml"
CUSTOM_URL: Final = f"{HOME}custom/feed.xml"
RUN_DAY: Final = date(2026, 7, 12)


def _rss(
    link: str = "https://paper.example/news/articleView.html?idxno=12345",
) -> bytes:
    return f"""<rss><channel><item>
        <title>Residents oppose city hall plan</title><link>{link}</link>
        <pubDate>Sun, 12 Jul 2026 05:00:00 +0900</pubDate>
    </item></channel></rss>""".encode()


@dataclass(frozen=True, slots=True)
class _Documents:
    """Return scripted documents and record typed requests in order."""

    scripted: dict[str, HttpDocument]
    requests: list[HttpRequest] = field(default_factory=list)

    def __call__(self, request: HttpRequest) -> HttpDocument:
        self.requests.append(request)
        assert request.url in self.scripted
        return self.scripted[request.url]


def _engine_unused(request: EngineRequest) -> EngineDocument:
    pytest.fail(f"engine must not run for {request.url}")


def _dependencies(documents: _Documents) -> FetchDependencies:
    def sleep(seconds: float) -> None:
        assert seconds == 0.5

    return FetchDependencies(documents, _engine_unused, sleep)


def test_healthy_first_fixed_rss_stops_with_bounded_request() -> None:
    # Given: the first standard RSS route is healthy.
    documents = _Documents({ALL_URL: HttpDocument(200, _rss(), ALL_URL)})

    # When: the single site is collected.
    result = collect_site(HOME, RUN_DAY, dependencies=_dependencies(documents))

    # Then: no later route runs and the request contract is bounded/descriptive.
    assert result.method == "requests"
    assert len(documents.requests) == 1
    request = documents.requests[0]
    assert request.url == ALL_URL
    assert dict(request.headers)["User-Agent"] == (
        "bal-gul/0.1 regional-news metadata collector"
    )
    assert request.follow_redirects
    assert request.timeout_seconds == 20.0
    assert request.max_bytes == 2 * 1024 * 1024


def test_advertised_same_site_feed_precedes_homepage_articles_and_engine() -> None:
    # Given: fixed feeds fail while the homepage advertises a healthy same-site feed.
    homepage = f"""<link rel="alternate" type="application/rss+xml"
        href="{CUSTOM_URL}"><a href="/news/articleView.html?idxno=99999">
        homepage article should lose</a>""".encode()
    documents = _Documents(
        {
            ALL_URL: HttpDocument(200, b"<rss>", ALL_URL),
            CLICK_URL: HttpDocument(200, b"<html>not XML</html>", CLICK_URL),
            HOME: HttpDocument(200, homepage, HOME),
            CUSTOM_URL: HttpDocument(200, _rss(), CUSTOM_URL),
        },
    )

    # When: requests-only discovery runs.
    result = collect_site(HOME, RUN_DAY, dependencies=_dependencies(documents))

    # Then: the advertised feed wins before homepage anchors or engine fallback.
    assert [request.url for request in documents.requests] == [
        ALL_URL,
        CLICK_URL,
        HOME,
        CUSTOM_URL,
    ]
    assert result.method == "requests"
    assert result.articles[0].link.endswith("idxno=12345")


@pytest.mark.parametrize(
    "meta",
    [
        '<meta charset="euc-kr">',
        '<meta http-equiv="Content-Type" content="text/html; charset=CP949">',
    ],
)
def test_html_meta_charset_precedes_iso_8859_1_response_default(meta: str) -> None:
    # Given: CP949 bytes declare a valid legacy Korean HTML charset.
    expected = f"{meta}<p>지역신문 민원 갈등</p>"
    document = HttpDocument(200, expected.encode("cp949"), HOME, "ISO-8859-1")

    # When: the transport boundary decodes the HTML document.
    decoded = fetch_transport.decode_html_document(document)

    # Then: the declared charset preserves Korean text exactly.
    assert decoded == expected


@pytest.mark.parametrize("codec", ["utf-8", "cp949"])
def test_html_without_meta_uses_strict_utf8_then_cp949(codec: str) -> None:
    # Given: a response has no meta charset and carries a misleading Latin-1 default.
    expected = "<p>지역신문 주민 반발</p>"
    document = HttpDocument(200, expected.encode(codec), HOME, "ISO-8859-1")

    # When: the deterministic fallback chain decodes the HTML.
    decoded = fetch_transport.decode_html_document(document)

    # Then: both UTF-8 and CP949 documents preserve the original Korean text.
    assert decoded == expected
