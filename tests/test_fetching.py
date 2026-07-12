"""Behavioral contracts for single-site fetching and runtime adapters."""

from dataclasses import dataclass, field
from datetime import date
from types import TracebackType
from typing import Final, Literal, Self
from unittest.mock import Mock

import pytest
import requests
from scraper import fetch_transport
from scraper.fetching import (
    DEFAULT_FETCH_DEPENDENCIES,
    EngineDocument,
    EngineRequest,
    FetchDependencies,
    FetchTransportError,
    HttpDocument,
    HttpRequest,
    SiteCollectionError,
    collect_site,
    get_engine_document,
    get_http_document,
)
from vendor.engine import FetchResult

HOME: Final = "https://paper.example/"
ALL_URL: Final = f"{HOME}rss/allArticle.xml"
CLICK_URL: Final = f"{HOME}rss/clickTop.xml"
RUN_DAY: Final = date(2026, 7, 12)
_NO_FAILURES: Final[frozenset[str]] = frozenset()


def _rss() -> bytes:
    return b"""<rss><channel><item>
        <title>Residents oppose city hall plan</title>
        <link>https://paper.example/news/articleView.html?idxno=12345</link>
        <description>summary</description>
        <pubDate>Sun, 12 Jul 2026 05:00:00 +0900</pubDate>
    </item></channel></rss>"""


@dataclass(frozen=True, slots=True)
class _ScriptedDocuments:
    """Return injected documents while recording order; list mutation is intentional."""

    documents: dict[str, HttpDocument]
    failures: frozenset[str] = frozenset()
    events: list[str] = field(default_factory=list)

    def __call__(self, request: HttpRequest) -> HttpDocument:
        self.events.append(f"get:{request.url}")
        if request.url in self.failures:
            raise FetchTransportError(
                url=request.url,
                method="requests",
                detail="timeout",
            )
        assert request.url in self.documents
        return self.documents[request.url]


def _dependencies(
    documents: _ScriptedDocuments,
    engine: EngineDocument,
) -> FetchDependencies:
    def get_engine(request: EngineRequest) -> EngineDocument:
        documents.events.append(f"engine:{request.url}")
        return engine

    def sleep(seconds: float) -> None:
        assert seconds == 0.5
        documents.events.append("sleep")

    return FetchDependencies(documents, get_engine, sleep)


def _invalid_documents(
    homepage: HttpDocument,
    failures: frozenset[str] = _NO_FAILURES,
) -> _ScriptedDocuments:
    return _ScriptedDocuments(
        {
            ALL_URL: HttpDocument(200, b"<rss>", ALL_URL),
            CLICK_URL: HttpDocument(200, b"<html>not XML</html>", CLICK_URL),
            HOME: homepage,
        },
        failures,
    )


def test_pacing_precedes_every_getter_and_transport_error_is_typed() -> None:
    # Given: one typed transport failure, one invalid feed, and valid homepage HTML.
    homepage = HttpDocument(
        200,
        b"""<article>
          <a href="/news/articleView.html?idxno=23456">valid article title</a>
          <time datetime="2026-07-12"></time>
        </article>""",
        HOME,
    )
    documents = _invalid_documents(homepage, frozenset({ALL_URL}))
    dependencies = _dependencies(
        documents,
        EngineDocument(ok=False, content="", final_url=HOME, stop_reason="unused"),
    )

    # When: the site is collected through the injected seam.
    result = collect_site(HOME, RUN_DAY, dependencies=dependencies)

    # Then: every getter is preceded by pacing and the typed failure is retained.
    assert documents.events == [
        "sleep",
        f"get:{ALL_URL}",
        "sleep",
        f"get:{CLICK_URL}",
        "sleep",
        f"get:{HOME}",
    ]
    assert result.method == "requests"
    assert result.attempts[0].reason == "transport_error"


def test_undated_article_homepage_is_a_zero_item_site_success() -> None:
    # Given: the homepage is structurally usable but exposes no publication date.
    homepage = HttpDocument(
        200,
        b'<a href="/news/articleView.html?idxno=23456">valid article title</a>',
        HOME,
    )
    documents = _invalid_documents(homepage)
    dependencies = _dependencies(
        documents,
        EngineDocument(ok=False, content="", final_url=HOME, stop_reason="unused"),
    )

    # When: undated metadata is collected.
    result = collect_site(HOME, RUN_DAY, dependencies=dependencies)

    # Then: no article is fabricated, while the accessible site still succeeds.
    assert result.method == "requests"
    assert result.articles == ()
    assert all(not event.startswith("engine:") for event in documents.events)
    assert result.attempts[-1].reason == "success"


def test_empty_and_oversized_injected_documents_are_rejected() -> None:
    # Given: empty and over-limit injected responses followed by engine failure.
    oversized = b"x" * ((2 * 1024 * 1024) + 1)
    documents = _ScriptedDocuments(
        {
            ALL_URL: HttpDocument(200, b"", ALL_URL),
            CLICK_URL: HttpDocument(200, oversized, CLICK_URL),
            HOME: HttpDocument(200, b"", HOME),
        },
    )
    dependencies = _dependencies(
        documents,
        EngineDocument(ok=False, content="", final_url=HOME, stop_reason="blocked"),
    )

    # When: no bounded document can be parsed.
    with pytest.raises(SiteCollectionError) as captured:
        _ = collect_site(HOME, RUN_DAY, dependencies=dependencies)

    # Then: bounded reasons and attempted engine use reach the typed failure.
    assert captured.value.engine_used
    assert tuple(attempt.reason for attempt in captured.value.attempts[:3]) == (
        "empty_document",
        "response_too_large",
        "empty_document",
    )


def test_engine_content_tries_feed_before_homepage_parser() -> None:
    # Given: requests routes fail and the engine returns RSS text.
    documents = _invalid_documents(HttpDocument(403, b"blocked", HOME))
    engine = EngineDocument(
        ok=True,
        content=_rss().decode(),
        final_url=HOME,
        stop_reason="success",
    )

    # When: engine content crosses the static parser boundary.
    result = collect_site(HOME, RUN_DAY, dependencies=_dependencies(documents, engine))

    # Then: the feed item succeeds without needing homepage-anchor syntax.
    assert result.method == "engine"
    assert result.engine_used
    assert result.articles[0].link.endswith("idxno=12345")


def test_reported_handoff_is_diagnostic_and_never_followed() -> None:
    # Given: a same-site meta handoff shell with no article metadata.
    shell = b'<meta http-equiv="refresh" content="0;url=/handoff">'
    documents = _invalid_documents(HttpDocument(200, shell, HOME))
    engine = EngineDocument(
        ok=False,
        content="",
        final_url=HOME,
        stop_reason="exhausted",
    )

    # When: the safe routes are exhausted.
    with pytest.raises(SiteCollectionError) as captured:
        _ = collect_site(HOME, RUN_DAY, dependencies=_dependencies(documents, engine))

    # Then: handoff is reported, while outbound requests remain on approved routes.
    assert any(
        attempt.reason == "reported_handoff" for attempt in captured.value.attempts
    )
    assert [event for event in documents.events if event.startswith("get:")] == [
        f"get:{ALL_URL}",
        f"get:{CLICK_URL}",
        f"get:{HOME}",
    ]


@dataclass(frozen=True, slots=True)
class _FakeResponse:
    """Minimal streaming requests response; mutation is unnecessary after setup."""

    chunks: tuple[bytes, ...]
    status_code: int = 200
    url: str = HOME
    encoding: str | None = "utf-8"

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        return False

    def iter_content(self, chunk_size: int) -> tuple[bytes, ...]:
        assert chunk_size > 0
        return self.chunks


def test_http_adapter_streams_bounded_response_and_maps_request_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a real adapter request and a fake requests response boundary.
    request = HttpRequest(
        url=HOME,
        headers=(("User-Agent", "test"),),
        timeout_seconds=3.0,
        follow_redirects=True,
        max_bytes=16,
    )
    get_mock = Mock(return_value=_FakeResponse((b"hello", b" world")))
    monkeypatch.setattr(requests, "get", get_mock)

    # When: the runtime adapter streams a bounded response.
    document = get_http_document(request)

    # Then: metadata maps exactly, and requests failures become typed failures.
    assert document == HttpDocument(200, b"hello world", HOME, "utf-8")
    get_mock.side_effect = requests.Timeout("late")
    with pytest.raises(FetchTransportError, match="late"):
        _ = get_http_document(request)


def test_engine_adapter_forwards_cloud_safe_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a vendored result and a narrow engine function replacement.
    result = FetchResult(ok=True, content="safe", final_url=HOME, stop_reason="success")
    fetch_mock = Mock(return_value=result)
    monkeypatch.setattr(fetch_transport, "engine_fetch", fetch_mock)

    # When: the runtime engine adapter executes its typed request.
    document = get_engine_document(EngineRequest(HOME))

    # Then: static output maps and every executable engine phase stays disabled.
    assert document == EngineDocument(
        ok=True,
        content="safe",
        final_url=HOME,
        stop_reason="success",
    )
    fetch_mock.assert_called_once_with(
        HOME,
        timeout=10,
        max_attempts=3,
        enable_playwright=False,
        enable_phase0=False,
        enable_learning=False,
    )


def test_default_dependencies_bind_runtime_adapters() -> None:
    assert DEFAULT_FETCH_DEPENDENCIES.document_getter is get_http_document
    assert DEFAULT_FETCH_DEPENDENCIES.engine_getter is get_engine_document
