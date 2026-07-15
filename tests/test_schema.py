from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Final

import pytest
from pydantic import ValidationError
from scraper.filtering import KeywordHits
from scraper.schema import (
    ArticleCandidate,
    CandidateFile,
    CandidateFilenameError,
    CandidateKeywordHits,
    CollectionFailure,
    CollectionStats,
    read_candidate_file,
    write_candidate_file,
)

KST: Final = timezone(timedelta(hours=9))
RUN_DATE: Final = date(2026, 7, 12)
GENERATED_AT: Final = datetime(2026, 7, 12, 6, 12, 34, tzinfo=KST)
COLLECTOR_SHA: Final = "1a2b3c4d5e6f789012345678901234567890abcd"


def _valid_hits() -> CandidateKeywordHits:
    return CandidateKeywordHits.from_keyword_hits(
        KeywordHits(youth_terms=("청년",), hardship_terms=("주거난",)),
    )


def _valid_candidate() -> ArticleCandidate:
    return ArticleCandidate(
        newspaper_name="강원일보",
        region="강원권",
        title="청년층, 주거난에 어려움",
        link="https://example.com/article/1",
        summary="월세 부담이 커졌다고 호소했다.",
        published=datetime(2026, 7, 12, 5, 30, tzinfo=KST),
        method="requests",
        keyword_hits=_valid_hits(),
    )


def _failures(count: int) -> tuple[CollectionFailure, ...]:
    return tuple(
        CollectionFailure(name=f"실패 신문 {index}", stop_reason="challenge")
        for index in range(count)
    )


def _document(
    *,
    stats: CollectionStats | None = None,
    candidates: tuple[ArticleCandidate, ...] | None = None,
    failures: tuple[CollectionFailure, ...] | None = None,
) -> CandidateFile:
    selected_candidates = (
        candidates if candidates is not None else (_valid_candidate(),)
    )
    selected_stats = stats or CollectionStats(
        sites_total=88,
        sites_succeeded=55,
        total=120,
        candidates=len(selected_candidates),
        engine_used=4,
    )
    return CandidateFile(
        run_date=RUN_DATE,
        generated_at=GENERATED_AT,
        workflow_run_url="https://github.com/acme/bal-gul/actions/runs/123",
        collector_commit_sha=COLLECTOR_SHA,
        candidates=selected_candidates,
        failures=failures if failures is not None else _failures(33),
        stats=selected_stats,
    )


def test_schema_production_surface_exists() -> None:
    assert Path("scraper/schema.py").is_file()


def test_exact_prd_json_shape_and_alias_round_trip() -> None:
    document = _document()

    encoded = document.model_dump_json(by_alias=True, indent=2)
    decoded = CandidateFile.model_validate_json(encoded)

    assert decoded == document
    assert tuple(document.model_dump(by_alias=True)) == (
        "run_date",
        "generated_at",
        "workflow_run_url",
        "collector_commit_sha",
        "candidates",
        "failures",
        "stats",
    )
    assert '"청년"' in encoded
    assert '"고충"' in encoded
    assert '"youth_terms"' not in encoded
    assert '"hardship_terms"' not in encoded
    assert "schema_version" not in encoded


def test_article_rejects_non_http_link_and_blank_required_text() -> None:
    candidate = _valid_candidate()
    encoded = candidate.model_dump_json(by_alias=True)

    with pytest.raises(ValidationError, match=r"HTTP\(S\)"):
        _ = ArticleCandidate.model_validate_json(
            encoded.replace("https://", "ftp://"),
        )
    with pytest.raises(ValidationError, match="newspaper_name"):
        _ = ArticleCandidate.model_validate_json(
            encoded.replace("강원일보", "   "),
        )


def test_article_requires_aware_published_timestamp_and_method_literal() -> None:
    candidate = _valid_candidate()
    encoded = candidate.model_dump_json(by_alias=True)

    with pytest.raises(ValidationError, match="timezone"):
        _ = ArticleCandidate.model_validate_json(
            encoded.replace("2026-07-12T05:30:00+09:00", "2026-07-12T05:30:00"),
        )
    with pytest.raises(ValidationError, match="requests"):
        _ = ArticleCandidate.model_validate_json(encoded.replace("requests", "browser"))

    without_summary = ArticleCandidate.model_validate_json(
        encoded.replace(f',"summary":"{candidate.summary}"', ""),
    )
    assert without_summary.summary == ""
    assert '"summary":""' in without_summary.model_dump_json(by_alias=True)


def test_keyword_hits_require_both_nonempty_unique_groups() -> None:
    with pytest.raises(ValidationError, match="too_short"):
        _ = CandidateKeywordHits.model_validate({"청년": (), "고충": ("주거난",)})
    with pytest.raises(ValidationError, match="unique"):
        _ = CandidateKeywordHits.model_validate(
            {"청년": ("청년", "청년"), "고충": ("주거난",)},
        )


def test_stats_require_exactly_88_sites_and_candidates_within_total() -> None:
    with pytest.raises(ValidationError, match="88"):
        _ = CollectionStats.model_validate_json(
            """{
                "sites_total": 87,
                "sites_succeeded": 55,
                "total": 1,
                "candidates": 1,
                "engine_used": 0
            }""",
        )
    with pytest.raises(ValidationError, match="cannot exceed total"):
        _ = CollectionStats(
            sites_total=88,
            sites_succeeded=55,
            total=1,
            candidates=2,
            engine_used=0,
        )
    assert (
        CollectionStats(
            sites_total=88,
            sites_succeeded=0,
            total=0,
            candidates=0,
            engine_used=88,
        ).engine_used
        == 88
    )


def test_document_rejects_stats_candidate_count_mismatch() -> None:
    stats = CollectionStats(
        sites_total=88,
        sites_succeeded=55,
        total=120,
        candidates=0,
        engine_used=4,
    )

    with pytest.raises(ValidationError, match="candidate tuple length"):
        _ = _document(stats=stats)


def test_document_requires_every_site_to_be_accounted_for() -> None:
    with pytest.raises(ValidationError, match="account for 88 sites"):
        _ = _document(failures=_failures(32))


def test_document_rejects_duplicate_failure_names_and_candidate_links() -> None:
    duplicate_failures = (*_failures(32), _failures(1)[0])
    candidate = _valid_candidate()
    duplicate_stats = CollectionStats(
        sites_total=88,
        sites_succeeded=55,
        total=120,
        candidates=2,
        engine_used=4,
    )

    with pytest.raises(ValidationError, match="failure names must be unique"):
        _ = _document(failures=duplicate_failures)
    with pytest.raises(ValidationError, match="candidate links must be unique"):
        _ = _document(stats=duplicate_stats, candidates=(candidate, candidate))


def test_generated_at_must_be_aware_and_match_run_date_in_kst() -> None:
    encoded = _document().model_dump_json(by_alias=True)

    with pytest.raises(ValidationError, match="timezone"):
        _ = CandidateFile.model_validate_json(
            encoded.replace("2026-07-12T06:12:34+09:00", "2026-07-12T06:12:34"),
        )
    with pytest.raises(ValidationError, match="KST date"):
        _ = CandidateFile.model_validate_json(
            encoded.replace("2026-07-12T06:12:34+09:00", "2026-07-11T23:00:00+09:00"),
        )


def test_collector_sha_is_full_lowercase_40_hex() -> None:
    encoded = _document().model_dump_json(by_alias=True)

    with pytest.raises(ValidationError, match="collector_commit_sha"):
        _ = CandidateFile.model_validate_json(encoded.replace(COLLECTOR_SHA, "ABC123"))


def test_writer_uses_dated_filename_trailing_newline_and_round_trips(
    tmp_path: Path,
) -> None:
    document = _document()

    output_path = write_candidate_file(document, tmp_path)

    assert output_path == tmp_path / "candidates-2026-07-12.json"
    assert output_path.read_bytes().endswith(b"\n")
    assert read_candidate_file(output_path) == document


def test_reader_rejects_filename_and_run_date_mismatch(tmp_path: Path) -> None:
    document = _document()
    wrong_path = tmp_path / "candidates-2026-07-11.json"
    _ = wrong_path.write_text(
        document.model_dump_json(by_alias=True),
        encoding="utf-8",
    )

    with pytest.raises(CandidateFilenameError, match=r"candidates-2026-07-12\.json"):
        _ = read_candidate_file(wrong_path)


def test_collection_threshold_accepts_zero_candidates_at_55_but_not_54() -> None:
    zero_candidates = ()
    ready_stats = CollectionStats(
        sites_total=88,
        sites_succeeded=55,
        total=0,
        candidates=0,
        engine_used=0,
    )
    low_stats = CollectionStats(
        sites_total=88,
        sites_succeeded=54,
        total=0,
        candidates=0,
        engine_used=0,
    )

    assert _document(
        stats=ready_stats,
        candidates=zero_candidates,
    ).meets_collection_threshold
    assert not _document(
        stats=low_stats,
        candidates=zero_candidates,
        failures=_failures(34),
    ).meets_collection_threshold


def test_models_are_frozen_strict_and_forbid_extra_fields() -> None:
    document = _document()

    with pytest.raises(ValidationError, match="frozen_instance"):
        delattr(document, "run_date")
    with pytest.raises(ValidationError, match="extra_forbidden"):
        _ = CandidateFile.model_validate_json(
            document.model_dump_json(by_alias=True)[:-1] + ',"issue_id":"Phase 3"}',
        )
    with pytest.raises(ValidationError, match="int_type"):
        _ = CollectionStats.model_validate(
            {
                "sites_total": 88,
                "sites_succeeded": "55",
                "total": 0,
                "candidates": 0,
                "engine_used": 0,
            },
        )
