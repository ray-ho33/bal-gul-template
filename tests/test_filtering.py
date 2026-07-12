from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from scraper.filtering import (
    AGENCY_KEYWORDS,
    CONFLICT_KEYWORDS,
    CurrentDayPublication,
    KeywordHits,
    find_keyword_hits,
    is_candidate,
    is_recent,
    parse_rss_timestamp,
)

KST = timezone(timedelta(hours=9))
RUN_ANCHOR = datetime(2026, 7, 12, 6, tzinfo=KST)


def test_keywords_are_exactly_the_binding_project_terms() -> None:
    assert CONFLICT_KEYWORDS == (
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
    assert AGENCY_KEYWORDS == (
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

    hits = find_keyword_hits("LH 상대 소송과 반발", "교육청 앞 시위")

    assert hits == KeywordHits(
        conflict_terms=("반발", "시위", "소송"),
        agency_terms=("교육청", "LH"),
    )
    with pytest.raises(FrozenInstanceError):
        delattr(hits, "conflict_terms")


def test_korean_place_agency_pattern_returns_tokens_without_obvious_noise() -> None:
    hits = find_keyword_hits(
        "춘천시가 철회를 요구받고 거제군은 반발에 직면",
        "경기도청에도 민원이 접수됐다",
    )

    assert hits.agency_terms == ("도청", "춘천시", "거제군", "경기도")
    assert find_keyword_hits("반드시 반대", "인지도 논란").agency_terms == ()
    assert find_keyword_hits("신제품 출시 논란", "도시 재생 반대").agency_terms == ()


def test_recent_articles_require_conflict_and_agency_hits() -> None:
    published_at = RUN_ANCHOR - timedelta(hours=1)

    assert not is_candidate(
        "주민 반발과 소송 예고",
        "대책을 요구했다",
        published_at=published_at,
        run_anchor=RUN_ANCHOR,
    )
    assert not is_candidate(
        "시청과 교육청의 공동 발표",
        "새 계획을 공개했다",
        published_at=published_at,
        run_anchor=RUN_ANCHOR,
    )
    assert is_candidate(
        "주민들이 사업에 반발",
        "시청에 재검토를 요구했다",
        published_at=published_at,
        run_anchor=RUN_ANCHOR,
    )

    hits = find_keyword_hits("주민들이 사업에 반발", "시청에 재검토를 요구했다")
    assert hits.conflict_terms == ("반발",)
    assert hits.agency_terms == ("시청",)
    assert hits.has_both_groups


def test_previous_24_hours_is_inclusive_and_excludes_stale_and_future() -> None:
    exact_boundary = RUN_ANCHOR - timedelta(hours=24)

    assert is_recent(exact_boundary, run_anchor=RUN_ANCHOR)
    assert not is_recent(
        exact_boundary - timedelta(microseconds=1),
        run_anchor=RUN_ANCHOR,
    )
    assert is_recent(RUN_ANCHOR, run_anchor=RUN_ANCHOR)
    assert not is_recent(
        RUN_ANCHOR + timedelta(microseconds=1),
        run_anchor=RUN_ANCHOR,
    )


def test_fresh_rfc_and_iso_timestamps_parse_as_aware_datetimes() -> None:
    iso_published_at = parse_rss_timestamp("2026-07-12T05:30:00+09:00")
    rfc_published_at = parse_rss_timestamp("Sun, 12 Jul 2026 05:30:00 +0900")

    assert iso_published_at.utcoffset() == timedelta(hours=9)
    assert rfc_published_at.utcoffset() == timedelta(hours=9)
    assert is_candidate(
        "LH 사업에 주민 반발",
        "",
        published_at=iso_published_at,
        run_anchor=RUN_ANCHOR,
    )
    assert is_candidate(
        "주민 시위",
        "교육청에 대책 촉구",
        published_at=rfc_published_at,
        run_anchor=RUN_ANCHOR,
    )


def test_rss_timestamp_must_be_parseable_and_timezone_aware() -> None:
    with pytest.raises(ValueError, match="parse RSS publication timestamp"):
        _ = parse_rss_timestamp("not a timestamp")
    with pytest.raises(ValueError, match="timezone-aware"):
        _ = parse_rss_timestamp("2026-07-12T05:30:00")


def test_html_item_uses_explicit_current_day_publication() -> None:
    current_day = CurrentDayPublication(date(2026, 7, 12))
    prior_day = CurrentDayPublication(date(2026, 7, 11))

    assert is_candidate(
        "시청 계획에 상인 반발",
        "",
        published_at=current_day,
        run_anchor=RUN_ANCHOR,
    )
    assert not is_candidate(
        "시청 계획에 상인 반발",
        "",
        published_at=prior_day,
        run_anchor=RUN_ANCHOR,
    )


def test_run_anchor_must_be_aware_kst() -> None:
    publication = RUN_ANCHOR - timedelta(hours=1)

    with pytest.raises(ValueError, match="timezone-aware"):
        _ = is_recent(publication, run_anchor=RUN_ANCHOR.replace(tzinfo=None))
    with pytest.raises(ValueError, match="KST"):
        _ = is_recent(publication, run_anchor=RUN_ANCHOR.astimezone(UTC))
