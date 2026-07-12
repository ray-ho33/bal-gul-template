"""Deterministic RSS, homepage, and engine routing for one newspaper."""

from dataclasses import dataclass
from datetime import date
from typing import ClassVar, Final
from urllib.parse import urljoin

from scraper.fetch_transport import (
    DEFAULT_FETCH_DEPENDENCIES,
    DocumentGetter,
    EngineDocument,
    EngineGetter,
    EngineRequest,
    FetchDependencies,
    FetchTransportError,
    HttpDocument,
    HttpRequest,
    Sleeper,
    decode_html_document,
    get_engine_document,
    get_http_document,
)
from scraper.parsing import (
    FeedParseError,
    RawArticle,
    discover_feed_urls,
    homepage_has_article_anchors,
    parse_feed,
    parse_homepage_articles,
    reported_handoff_url,
)
from scraper.schema import CollectionMethod

_PACE_SECONDS: Final = 0.5
_TIMEOUT_SECONDS: Final = 20.0
_MAX_BYTES: Final = 2 * 1024 * 1024
_HTTP_SUCCESS_MIN: Final = 200
_HTTP_REDIRECT_MIN: Final = 300
_HEADERS: Final = (
    ("User-Agent", "bal-gul/0.1 regional-news metadata collector"),
    ("Accept", "application/rss+xml, application/xml, text/html;q=0.9, */*;q=0.5"),
)


@dataclass(frozen=True, slots=True)
class FetchAttempt:
    """One stable route diagnostic without fetched content."""

    url: str
    method: CollectionMethod
    reason: str
    detail: str


@dataclass(frozen=True, slots=True)
class SiteCollectionError(Exception):
    """Every safe route failed to produce article metadata."""

    stop_reason: str
    attempts: tuple[FetchAttempt, ...]
    engine_used: bool

    def __post_init__(self) -> None:
        """Initialize the exception message from the stable terminal reason."""
        Exception.__init__(self, f"site collection failed: {self.stop_reason}")


@dataclass(frozen=True, slots=True)
class SiteCollection:
    """One structurally parsed site payload and its collection diagnostics."""

    articles: tuple[RawArticle, ...]
    method: CollectionMethod
    engine_used: bool
    attempts: tuple[FetchAttempt, ...]


class _SiteRun:
    """Accumulate one site's bounded route attempts; mutation is intentional."""

    __slots__: ClassVar[tuple[str, ...]] = ("attempts", "dependencies")

    attempts: list[FetchAttempt]
    dependencies: FetchDependencies

    def __init__(self, dependencies: FetchDependencies) -> None:
        self.dependencies = dependencies
        self.attempts = []

    def record(self, attempt: FetchAttempt) -> None:
        """Append one content-free route diagnostic."""
        self.attempts.append(attempt)

    def document(self, url: str) -> HttpDocument | None:
        """Pace, fetch, and enforce one injected HTTP document boundary."""
        request = HttpRequest(
            url=url,
            headers=_HEADERS,
            timeout_seconds=_TIMEOUT_SECONDS,
            follow_redirects=True,
            max_bytes=_MAX_BYTES,
        )
        self.dependencies.sleeper(_PACE_SECONDS)
        try:
            document = self.dependencies.document_getter(request)
        except FetchTransportError as error:
            self.record(FetchAttempt(url, "requests", "transport_error", error.detail))
            return None
        if not document.content:
            self.record(FetchAttempt(url, "requests", "empty_document", "0 bytes"))
            return None
        if len(document.content) > request.max_bytes:
            detail = f"response exceeds {request.max_bytes} bytes"
            self.record(FetchAttempt(url, "requests", "response_too_large", detail))
            return None
        return document

    def feed(self, url: str) -> SiteCollection | None:
        """Return a nonempty feed collection or record why it was unusable."""
        document = self.document(url)
        if document is None:
            return None
        if not _HTTP_SUCCESS_MIN <= document.status_code < _HTTP_REDIRECT_MIN:
            self.record(
                FetchAttempt(url, "requests", "http_status", str(document.status_code))
            )
            return None
        try:
            articles = parse_feed(document.content)
        except FeedParseError as error:
            self.record(
                FetchAttempt(url, "requests", error.reason.value, "feed rejected")
            )
            return None
        self.record(
            FetchAttempt(url, "requests", "success", f"articles={len(articles)}")
        )
        return _site_collection(articles, "requests", self)


def collect_site(
    homepage: str,
    run_day: date,
    *,
    dependencies: FetchDependencies = DEFAULT_FETCH_DEPENDENCIES,
) -> SiteCollection:
    """Collect one site through fixed RSS, HTML, then safe engine routes."""
    run = _SiteRun(dependencies)
    requests_result = _collect_with_requests(homepage, run_day, run)
    if requests_result is not None:
        return requests_result
    return _collect_with_engine(homepage, run_day, run)


def _collect_with_requests(
    homepage: str,
    run_day: date,
    run: _SiteRun,
) -> SiteCollection | None:
    for path in ("/rss/allArticle.xml", "/rss/clickTop.xml"):
        result = run.feed(urljoin(homepage, path))
        if result is not None:
            return result

    document = run.document(homepage)
    if document is None:
        return None
    if not _HTTP_SUCCESS_MIN <= document.status_code < _HTTP_REDIRECT_MIN:
        run.record(
            FetchAttempt(homepage, "requests", "http_status", str(document.status_code))
        )
        return None
    base_url = document.final_url or homepage
    html = decode_html_document(document)
    for discovered_url in discover_feed_urls(html, base_url):
        result = run.feed(discovered_url)
        if result is not None:
            return result
    articles = parse_homepage_articles(html, base_url, run_day)
    if articles or homepage_has_article_anchors(html, base_url):
        run.record(
            FetchAttempt(homepage, "requests", "success", f"articles={len(articles)}"),
        )
        return _site_collection(articles, "requests", run)
    _record_handoff(html, base_url, run)
    run.record(
        FetchAttempt(homepage, "requests", "zero_valid_items", "homepage rejected")
    )
    return None


def _collect_with_engine(
    homepage: str,
    run_day: date,
    run: _SiteRun,
) -> SiteCollection:
    request = EngineRequest(url=homepage)
    run.dependencies.sleeper(_PACE_SECONDS)
    try:
        document = run.dependencies.engine_getter(request)
    except FetchTransportError as error:
        run.record(FetchAttempt(homepage, "engine", "transport_error", error.detail))
        reason = "engine_transport_error"
        raise _engine_error(reason, run) from error
    if not document.ok:
        reason = document.stop_reason.strip() or "engine_failed"
        run.record(FetchAttempt(homepage, "engine", "engine_failure", reason))
        raise _engine_error(reason, run)

    base_url = document.final_url or homepage
    try:
        articles = parse_feed(document.content.encode())
    except FeedParseError:
        _record_handoff(document.content, base_url, run)
        articles = parse_homepage_articles(document.content, base_url, run_day)
    if not articles and not homepage_has_article_anchors(document.content, base_url):
        run.record(
            FetchAttempt(homepage, "engine", "zero_valid_items", "content rejected")
        )
        reason = "engine_zero_valid_items"
        raise _engine_error(reason, run)
    run.record(FetchAttempt(homepage, "engine", "success", f"articles={len(articles)}"))
    return _site_collection(articles, "engine", run)


def _site_collection(
    articles: tuple[RawArticle, ...],
    method: CollectionMethod,
    run: _SiteRun,
) -> SiteCollection:
    return SiteCollection(
        articles=articles,
        method=method,
        engine_used=method == "engine",
        attempts=tuple(run.attempts),
    )


def _engine_error(reason: str, run: _SiteRun) -> SiteCollectionError:
    return SiteCollectionError(
        stop_reason=reason,
        attempts=tuple(run.attempts),
        engine_used=True,
    )


def _record_handoff(html: str, base_url: str, run: _SiteRun) -> None:
    handoff = reported_handoff_url(html, base_url)
    if handoff is not None:
        run.record(FetchAttempt(base_url, "requests", "reported_handoff", handoff))


__all__: Final = (
    "DEFAULT_FETCH_DEPENDENCIES",
    "DocumentGetter",
    "EngineDocument",
    "EngineGetter",
    "EngineRequest",
    "FetchAttempt",
    "FetchDependencies",
    "FetchTransportError",
    "HttpDocument",
    "HttpRequest",
    "SiteCollection",
    "SiteCollectionError",
    "Sleeper",
    "collect_site",
    "decode_html_document",
    "get_engine_document",
    "get_http_document",
)
