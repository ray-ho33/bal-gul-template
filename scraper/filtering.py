"""Deterministic time and keyword filtering for collected article metadata."""

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Final, TypeAlias

CONFLICT_KEYWORDS: Final[tuple[str, ...]] = (
    "갈등",
    "반발",
    "반대",
    "항의",
    "규탄",
    "시위",
    "집회",
    "소송",
    "행정심판",
    "철회",
    "논란",
    "마찰",
    "충돌",
    "진정",
    "탄원",
    "민원",
)
AGENCY_KEYWORDS: Final[tuple[str, ...]] = (
    "시청",
    "도청",
    "군청",
    "구청",
    "시장",
    "도지사",
    "정부",
    "부처",
    "지자체",
    "교육청",
    "경찰",
    "공사",
    "공단",
    "LH",
    "국토부",
    "환경부",
)

_KST_OFFSET: Final = timedelta(hours=9)
_RECENT_WINDOW: Final = timedelta(hours=24)
_PLACE_AGENCY_PATTERN: Final = re.compile(
    r"""
    (?<![가-힣])
    (?P<agency>[가-힣]{2,8}?(?:시|군|도))
    (?=
        (?:청)?
        (?:에서는|에서도|으로는|로는|에도|에서|으로|까지|부터)?
        (?:의|에|와|과|로|은|는|이|가|을|를|도|만|측)?
        (?:[^가-힣]|$)
    )
    """,
    re.VERBOSE,
)
_OBVIOUS_NON_PLACE_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "반드시",
        "보상제도",
        "선호도",
        "신뢰도",
        "연합군",
        "완성도",
        "인지도",
        "정확도",
        "지원제도",
        "활용도",
    },
)


@dataclass(frozen=True, slots=True)
class KeywordHits:
    """Conflict and agency terms found in an article title and summary."""

    conflict_terms: tuple[str, ...]
    agency_terms: tuple[str, ...]

    @property
    def has_both_groups(self) -> bool:
        """Return whether at least one term from each keyword group matched."""
        return bool(self.conflict_terms and self.agency_terms)


@dataclass(frozen=True, slots=True)
class CurrentDayPublication:
    """Explicit date-only evidence for an untimestamped HTML item."""

    day: date


PublicationTime: TypeAlias = datetime | CurrentDayPublication


def find_keyword_hits(title: str, summary: str) -> KeywordHits:
    """Return all configured keyword hits from title and summary only."""
    searchable_text = f"{title}\n{summary}".casefold()
    conflict_terms = tuple(
        term for term in CONFLICT_KEYWORDS if term.casefold() in searchable_text
    )
    agency_terms = tuple(
        term for term in AGENCY_KEYWORDS if term.casefold() in searchable_text
    )
    place_agency_terms = tuple(
        dict.fromkeys(
            match.group("agency")
            for match in _PLACE_AGENCY_PATTERN.finditer(searchable_text)
            if match.group("agency") not in _OBVIOUS_NON_PLACE_TOKENS
        ),
    )
    return KeywordHits(
        conflict_terms=conflict_terms,
        agency_terms=agency_terms + place_agency_terms,
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
    """Return whether an article is recent and hits both keyword groups."""
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
