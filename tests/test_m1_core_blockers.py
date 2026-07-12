"""Regression tests for audited collector isolation and engine bounds."""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Final
from unittest.mock import Mock

import pytest
from scraper import collector, fetch_transport
from scraper.collector import (
    CollectionProgress,
    CollectionRequest,
    CollectorDependencies,
    collect_candidates,
)
from scraper.fetch_transport import (
    EngineRequest,
    FetchTransportError,
    get_engine_document,
)
from scraper.fetching import SiteCollection
from scraper.filtering import KeywordHits
from scraper.filtering import find_keyword_hits as real_find_keyword_hits
from scraper.parsing import RawArticle
from scraper.registry import NewspaperSource
from vendor.engine import FetchResult

KST: Final = timezone(timedelta(hours=9))
RUN_DAY: Final = date(2026, 7, 12)
ANCHOR: Final = datetime(2026, 7, 12, 6, tzinfo=KST)
HOME: Final = "https://paper.example/"
SOURCES: Final = tuple(
    NewspaperSource(
        name=f"신문 {index}",
        region="테스트권",
        homepage=f"https://site-{index}.example/",
    )
    for index in range(69)
)


def _stale_collection() -> SiteCollection:
    article = RawArticle(
        title="주민 반발",
        link="https://news.example/stale",
        summary="군청 철회",
        published=ANCHOR - timedelta(hours=25),
    )
    return SiteCollection(
        articles=(article,),
        method="requests",
        engine_used=False,
        attempts=(),
    )


@dataclass(frozen=True, slots=True)
class _CrashingFetcher:
    """Crash one site unexpectedly while recording every attempted source."""

    crash_url: str
    calls: list[str] = field(default_factory=list)

    def __call__(self, homepage: str, run_day: date) -> SiteCollection:
        self.calls.append(homepage)
        assert run_day == RUN_DAY
        if homepage == self.crash_url:
            message = "unexpected parser defect"
            raise RuntimeError(message)
        return _stale_collection()


def _ignore_progress(progress: CollectionProgress) -> None:
    _ = progress


def test_unexpected_site_exception_is_logged_bounded_and_isolated(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Given: one implementation defect before many later newspaper sites.
    crashed = SOURCES[4]
    fetcher = _CrashingFetcher(crashed.homepage)
    request = CollectionRequest(RUN_DAY, ANCHOR, None, "a" * 40)
    dependencies = CollectorDependencies(fetcher, lambda: ANCHOR, _ignore_progress)

    # When: the complete registry is collected.
    document = collect_candidates(SOURCES, request, dependencies)

    # Then: the defect has a bounded public reason and a full diagnostic trace.
    assert fetcher.calls == [source.homepage for source in SOURCES]
    assert document.stats.sites_succeeded == 68
    assert document.failures[0].name == crashed.name
    assert document.failures[0].stop_reason == "collector_exception:RuntimeError"
    assert "Traceback (most recent call last)" in caplog.text
    assert "RuntimeError: unexpected parser defect" in caplog.text


def test_unexpected_per_site_aggregation_exception_is_also_isolated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: fetched metadata triggers an unexpected filtering defect at one site.
    malformed = RawArticle(
        title="aggregation crash",
        link="https://news.example/malformed",
        summary="군청 철회",
        published=ANCHOR,
    )
    calls: list[str] = []

    def find_keyword_hits(title: str, summary: str) -> KeywordHits:
        if title == malformed.title:
            message = "aggregation defect"
            raise RuntimeError(message)
        return real_find_keyword_hits(title, summary)

    monkeypatch.setattr(collector, "find_keyword_hits", find_keyword_hits)

    def fetch(homepage: str, run_day: date) -> SiteCollection:
        calls.append(homepage)
        assert run_day == RUN_DAY
        if homepage == SOURCES[4].homepage:
            return SiteCollection(
                articles=(malformed,),
                method="requests",
                engine_used=False,
                attempts=(),
            )
        return _stale_collection()

    dependencies = CollectorDependencies(fetch, lambda: ANCHOR, _ignore_progress)

    # When: aggregation crosses the per-site isolation boundary.
    document = collect_candidates(
        SOURCES,
        CollectionRequest(RUN_DAY, ANCHOR, None, "a" * 40),
        dependencies,
    )

    # Then: later sources still run and the malformed site is accounted as failed.
    assert calls == [source.homepage for source in SOURCES]
    assert document.stats.sites_succeeded == 68
    assert document.failures[0].stop_reason == "collector_exception:RuntimeError"


def test_engine_request_forwards_explicit_runtime_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a successful static result and the default bounded engine request.
    result = FetchResult(ok=True, content="safe", final_url=HOME, stop_reason="ok")
    fetch_mock = Mock(return_value=result)
    monkeypatch.setattr(fetch_transport, "engine_fetch", fetch_mock)

    # When: the engine adapter runs.
    document = get_engine_document(EngineRequest(HOME))

    # Then: it overrides exhaustive vendor defaults and keeps cloud phases off.
    assert (document.content, document.final_url) == ("safe", HOME)
    fetch_mock.assert_called_once_with(
        HOME,
        timeout=10,
        max_attempts=3,
        enable_playwright=False,
        enable_phase0=False,
        enable_learning=False,
    )
    assert EngineRequest(HOME).max_bytes == 2 * 1024 * 1024


def test_engine_utf8_output_over_byte_cap_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: two Korean characters whose UTF-8 payload exceeds a five-byte cap.
    result = FetchResult(ok=True, content="가가", final_url=HOME, stop_reason="ok")
    monkeypatch.setattr(fetch_transport, "engine_fetch", Mock(return_value=result))

    # When/Then: byte size, not Python character count, enforces the boundary.
    with pytest.raises(FetchTransportError, match="exceeds 5 bytes"):
        _ = get_engine_document(EngineRequest(HOME, max_bytes=5))
