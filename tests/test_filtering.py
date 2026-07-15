from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from scraper.filtering import (
    HARDSHIP_KEYWORDS,
    YOUTH_KEYWORDS,
    CurrentDayPublication,
    KeywordHits,
    find_keyword_hits,
    is_candidate,
    is_recent,
    parse_rss_timestamp,
)

KST = timezone(timedelta(hours=9))
RUN_ANCHOR = datetime(2026, 7, 12, 6, tzinfo=KST)


def test_youth_and_hardship_keywords_are_the_binding_project_terms() -> None:
    # Given
    expected_youth_keywords = (
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
    expected_hardship_keywords = (
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

    # When
    hits = find_keyword_hits(
        "2030 사회초년생 덮친 주거난",
        "월세 부담으로 고립 위험까지 커졌다",
    )

    # Then
    assert expected_youth_keywords == YOUTH_KEYWORDS
    assert expected_hardship_keywords == HARDSHIP_KEYWORDS
    assert hits == KeywordHits(
        youth_terms=("2030", "사회초년생"),
        hardship_terms=("부담", "고립", "주거난", "월세"),
    )
    with pytest.raises(FrozenInstanceError):
        delattr(hits, "youth_terms")


def test_recent_articles_require_youth_and_hardship_hits() -> None:
    # Given
    published_at = RUN_ANCHOR - timedelta(hours=1)

    # When / Then
    assert not is_candidate(
        "월세 부담과 주거난 심화",
        "지원 대책이 필요하다는 지적이다",
        published_at=published_at,
        run_anchor=RUN_ANCHOR,
    )
    assert not is_candidate(
        "청년 창업 축제 성료",
        "참가자들이 새 사업을 소개했다",
        published_at=published_at,
        run_anchor=RUN_ANCHOR,
    )
    assert is_candidate(
        "20대 구직자 취업난 장기화",
        "생활고까지 겹쳐 막막하다고 호소했다",
        published_at=published_at,
        run_anchor=RUN_ANCHOR,
    )

    hits = find_keyword_hits(
        "20대 구직자 취업난 장기화",
        "생활고까지 겹쳐 막막하다고 호소했다",
    )
    assert hits.youth_terms == ("20대",)
    assert hits.hardship_terms == ("생활고", "취업난", "막막")
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
        "청년층 전세사기 피해",
        "",
        published_at=iso_published_at,
        run_anchor=RUN_ANCHOR,
    )
    assert is_candidate(
        "30대 직장인 번아웃",
        "과로와 스트레스로 어려움을 겪는다",
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
        "청년층 월세 부담 커져",
        "",
        published_at=current_day,
        run_anchor=RUN_ANCHOR,
    )
    assert not is_candidate(
        "청년층 월세 부담 커져",
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
