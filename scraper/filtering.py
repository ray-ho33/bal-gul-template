"""Deterministic time and topic filtering for collected article metadata."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Final, TypeAlias

YOUTH_KEYWORDS: Final[tuple[str, ...]] = (
    "청년",
    "2030",
    "20대",
    "30대",
    "20·30대",
    "20~30대",
    "20-30대",
    "MZ세대",
    "사회초년생",
    "취업준비생",
    "취준생",
    "대학생",
)
HARDSHIP_KEYWORDS: Final[tuple[str, ...]] = (
    "고충",
    "어렵",
    "힘들",
    "곤란",
    "부담",
    "불안",
    "위기",
    "피해",
    "차별",
    "고립",
    "은둔",
    "빈곤",
    "생활고",
    "실업",
    "취업난",
    "구직난",
    "주거난",
    "전세사기",
    "월세",
    "학자금",
    "부채",
    "빚",
    "저임금",
    "임금체불",
    "과로",
    "해고",
    "번아웃",
    "소진",
    "스트레스",
    "우울",
    "자살",
    "포기",
    "막막",
)

_KST_OFFSET: Final = timedelta(hours=9)
_RECENT_WINDOW: Final = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class KeywordHits:
    """Youth and hardship terms found in an article title and summary."""

    youth_terms: tuple[str, ...]
    hardship_terms: tuple[str, ...]

    @property
    def has_both_groups(self) -> bool:
        """Return whether at least one term from each keyword group matched."""
        return bool(self.youth_terms and self.hardship_terms)


@dataclass(frozen=True, slots=True)
class CurrentDayPublication:
    """Explicit date-only evidence for an untimestamped HTML item."""

    day: date


PublicationTime: TypeAlias = datetime | CurrentDayPublication


def find_keyword_hits(title: str, summary: str) -> KeywordHits:
    """Return all configured keyword hits from title and summary only."""
    searchable_text = f"{title}\n{summary}".casefold()
    youth_terms = tuple(
        term for term in YOUTH_KEYWORDS if term.casefold() in searchable_text
    )
    hardship_terms = tuple(
        term for term in HARDSHIP_KEYWORDS if term.casefold() in searchable_text
    )
    return KeywordHits(
        youth_terms=youth_terms,
        hardship_terms=hardship_terms,
    )


def parse_rss_timestamp(value: str) -> datetime:
    """Parse an ISO-8601 or RFC-style RSS timestamp as an aware datetime."""
    timestamp = value.strip()
    if not timestamp:
        raise _timestamp_parse_error(value)

    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError:
        try:
            parsed = parsedate_to_datetime(timestamp)
        except (TypeError, ValueError, OverflowError) as rfc_error:
            raise _timestamp_parse_error(value) from rfc_error

    return _require_aware(parsed, name="RSS publication timestamp")


def is_recent(published_at: PublicationTime, *, run_anchor: datetime) -> bool:
    """Return whether publication falls in the anchored previous 24 hours."""
    anchor = _require_kst_anchor(run_anchor)
    if isinstance(published_at, CurrentDayPublication):
        return published_at.day == anchor.date()

    publication = _require_aware(published_at, name="publication timestamp")
    lower_bound = anchor - _RECENT_WINDOW
    return lower_bound <= publication <= anchor


def is_candidate(
    title: str,
    summary: str,
    *,
    published_at: PublicationTime,
    run_anchor: datetime,
) -> bool:
    """Return whether a recent article has both youth and hardship terms."""
    recent = is_recent(published_at, run_anchor=run_anchor)
    hits = find_keyword_hits(title, summary)
    return recent and hits.has_both_groups


def _require_aware(value: datetime, *, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise _timezone_error(name)
    return value


def _require_kst_anchor(value: datetime) -> datetime:
    anchor = _require_aware(value, name="run anchor")
    if anchor.utcoffset() != _KST_OFFSET:
        raise _kst_anchor_error()
    return anchor


def _timestamp_parse_error(value: str) -> ValueError:
    return ValueError(f"could not parse RSS publication timestamp: {value!r}")


def _timezone_error(name: str) -> ValueError:
    return ValueError(f"{name} must be timezone-aware")


def _kst_anchor_error() -> ValueError:
    return ValueError("run anchor must use KST (UTC+09:00)")
