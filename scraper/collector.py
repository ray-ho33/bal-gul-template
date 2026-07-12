"""Sequential aggregation of typed site metadata into the daily handoff."""

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import ClassVar, Final, Literal, Protocol

from scraper.fetching import SiteCollection, SiteCollectionError
from scraper.filtering import CurrentDayPublication, find_keyword_hits, is_recent
from scraper.registry import NewspaperSource
from scraper.schema import (
    ArticleCandidate,
    CandidateFile,
    CandidateKeywordHits,
    CollectionFailure,
    CollectionStats,
)

_KST: Final = timezone(timedelta(hours=9))
_SITE_TOTAL: Final = 69
_EXCEPTION_TYPE_MAX: Final = 64
_LOGGER: Final = logging.getLogger(__name__)


class SiteFetcher(Protocol):
    """Collect one newspaper homepage into a typed site payload."""

    def __call__(self, homepage: str, run_day: date) -> SiteCollection:
        """Return parsed metadata or raise a typed site failure."""
        ...


class GeneratedClock(Protocol):
    """Supply the completion timestamp after the final site."""

    def __call__(self) -> datetime:
        """Return one aware generated timestamp."""
        ...


@dataclass(frozen=True, slots=True)
class CollectionProgress:
    """Bounded count-only progress safe for external observation."""

    sites_completed: int
    sites_total: Literal[69]
    sites_succeeded: int
    sites_failed: int
    engine_used: int


class ProgressObserver(Protocol):
    """Consume count-only collection progress."""

    def __call__(self, progress: CollectionProgress) -> None:
        """Observe one completed-site checkpoint."""
        ...


@dataclass(frozen=True, slots=True)
class CollectionRequest:
    """Explicit metadata and time anchor for one daily collection run."""

    run_date: date
    run_anchor: datetime
    workflow_run_url: str | None
    collector_commit_sha: str


@dataclass(frozen=True, slots=True)
class CollectorDependencies:
    """Injected outbound collection, completion clock, and progress observer."""

    site_fetcher: SiteFetcher
    generated_clock: GeneratedClock
    observer: ProgressObserver


class _ArticleAggregation:
    """Accumulate recent candidates; mutation is the batch's explicit purpose."""

    __slots__: ClassVar[tuple[str, ...]] = (
        "candidates",
        "recent_links",
        "recent_total",
        "run_anchor",
    )

    run_anchor: datetime
    candidates: list[ArticleCandidate]
    recent_links: set[str]
    recent_total: int

    def __init__(self, run_anchor: datetime) -> None:
        """Create an empty accumulator for one explicit run anchor."""
        self.run_anchor = run_anchor
        self.candidates = []
        self.recent_links = set()
        self.recent_total = 0

    def accept(self, source: NewspaperSource, collection: SiteCollection) -> None:
        """Filter and append one successful site's article metadata in order."""
        candidates: list[ArticleCandidate] = []
        recent_links: set[str] = set()
        for article in collection.articles:
            if not is_recent(article.published, run_anchor=self.run_anchor):
                continue
            if article.link in self.recent_links or article.link in recent_links:
                continue
            recent_links.add(article.link)
            hits = find_keyword_hits(article.title, article.summary)
            if not hits.has_both_groups:
                continue

            if isinstance(article.published, CurrentDayPublication):
                published = datetime.combine(
                    article.published.day,
                    time.min,
                    tzinfo=_KST,
                )
            else:
                published = article.published.astimezone(_KST)
            candidates.append(
                ArticleCandidate(
                    newspaper_name=source.name,
                    region=source.region,
                    title=article.title,
                    link=article.link,
                    summary=article.summary,
                    published=published,
                    method=collection.method,
                    keyword_hits=CandidateKeywordHits.from_keyword_hits(hits),
                ),
            )
        self.recent_links.update(recent_links)
        self.recent_total += len(recent_links)
        self.candidates.extend(candidates)


def collect_candidates(
    sources: tuple[NewspaperSource, ...],
    request: CollectionRequest,
    dependencies: CollectorDependencies,
) -> CandidateFile:
    """Collect all supplied sources in order and build the exact handoff model."""
    articles = _ArticleAggregation(run_anchor=request.run_anchor)
    failures: list[CollectionFailure] = []
    sites_succeeded = 0
    engine_sites = 0

    for sites_completed, source in enumerate(sources, start=1):
        try:
            collection = dependencies.site_fetcher(
                source.homepage,
                request.run_date,
            )
            if collection.engine_used:
                engine_sites += 1
            articles.accept(source, collection)
        except SiteCollectionError as error:
            if error.engine_used:
                engine_sites += 1
            failures.append(
                CollectionFailure(
                    name=source.name,
                    stop_reason=error.stop_reason,
                ),
            )
        # PRD site isolation deliberately catches unknown implementation defects at
        # this one fetch-and-aggregate boundary; control-flow BaseExceptions propagate.
        except Exception as error:  # noqa: BLE001, RUF100  # noqa: BROAD_EXCEPT_OK
            error_type = type(error).__name__[:_EXCEPTION_TYPE_MAX] or "Exception"
            _LOGGER.exception(
                "Unexpected collector exception for %s (%s)",
                source.name,
                source.homepage,
            )
            failures.append(
                CollectionFailure(
                    name=source.name,
                    stop_reason=f"collector_exception:{error_type}",
                ),
            )
        else:
            sites_succeeded += 1

        dependencies.observer(
            CollectionProgress(
                sites_completed=sites_completed,
                sites_total=_SITE_TOTAL,
                sites_succeeded=sites_succeeded,
                sites_failed=len(failures),
                engine_used=engine_sites,
            ),
        )

    generated_at = dependencies.generated_clock()
    return CandidateFile(
        run_date=request.run_date,
        generated_at=generated_at,
        workflow_run_url=request.workflow_run_url,
        collector_commit_sha=request.collector_commit_sha,
        candidates=tuple(articles.candidates),
        failures=tuple(failures),
        stats=CollectionStats(
            sites_total=_SITE_TOTAL,
            sites_succeeded=sites_succeeded,
            total=articles.recent_total,
            candidates=len(articles.candidates),
            engine_used=engine_sites,
        ),
    )


__all__: Final = (
    "CollectionProgress",
    "CollectionRequest",
    "CollectorDependencies",
    "GeneratedClock",
    "ProgressObserver",
    "SiteFetcher",
    "collect_candidates",
)
