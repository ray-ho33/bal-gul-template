from collections.abc import Mapping
from datetime import date, datetime
from io import StringIO
from pathlib import Path
from typing import final
from zoneinfo import ZoneInfo

import pytest
from scraper.collect_runtime import RuntimeDependencies, run
from scraper.collector import (
    CollectionProgress,
    CollectionRequest,
    CollectorDependencies,
)
from scraper.fetching import SiteCollection
from scraper.registry import NewspaperSource
from scraper.schema import (
    CandidateFile,
    CollectionFailure,
    CollectionStats,
    read_candidate_file,
    write_candidate_file,
)

_KST = ZoneInfo("Asia/Seoul")
_SOURCE = NewspaperSource(
    name="테스트신문",
    region="테스트권",
    homepage="https://example.com",
)


def _empty_environment() -> dict[str, str]:
    return {}


@final
class _Harness:
    __slots__ = (
        "environment",
        "events",
        "fail_write",
        "loaded_path",
        "request",
        "root",
        "stderr",
        "stdout",
        "succeeded",
        "times",
        "written",
    )

    def __init__(
        self,
        root: Path,
        succeeded: int = 55,
        environment: Mapping[str, str] | None = None,
        *,
        fail_write: bool = False,
    ) -> None:
        self.root = root
        self.succeeded = succeeded
        self.environment = _empty_environment() if environment is None else environment
        self.times = [
            datetime(2026, 7, 12, 6, tzinfo=_KST),
            datetime(2026, 7, 12, 6, 20, tzinfo=_KST),
        ]
        self.stdout = StringIO()
        self.stderr = StringIO()
        self.events: list[str] = []
        self.loaded_path: Path | None = None
        self.request: CollectionRequest | None = None
        self.written: CandidateFile | None = None
        self.fail_write = fail_write

    def dependencies(self) -> RuntimeDependencies:
        return RuntimeDependencies(
            repo_root=self.root,
            environment=self.environment,
            clock=self.clock,
            registry_loader=self.load_sources,
            candidate_collector=self.collect,
            candidate_writer=self.write,
            sha_fallback=self.fallback_sha,
            site_fetcher=self.fetch_site,
            stdout=self.stdout,
            stderr=self.stderr,
        )

    def clock(self) -> datetime:
        self.events.append("clock")
        return self.times.pop(0)

    def load_sources(self, path: Path) -> tuple[NewspaperSource, ...]:
        self.events.append("registry")
        self.loaded_path = path
        return (_SOURCE,)

    def fallback_sha(self, repo_root: Path) -> str:
        assert repo_root == self.root
        self.events.append("sha")
        return "a" * 40

    def fetch_site(self, homepage: str, run_day: date) -> SiteCollection:
        raise AssertionError((homepage, run_day))

    def collect(
        self,
        sources: tuple[NewspaperSource, ...],
        request: CollectionRequest,
        dependencies: CollectorDependencies,
    ) -> CandidateFile:
        assert sources == (_SOURCE,)
        self.events.append("collect")
        self.request = request
        failed = 69 - self.succeeded
        dependencies.observer(
            CollectionProgress(
                sites_completed=69,
                sites_total=69,
                sites_succeeded=self.succeeded,
                sites_failed=failed,
                engine_used=2,
            ),
        )
        generated = dependencies.generated_clock()
        return CandidateFile(
            run_date=request.run_date,
            generated_at=generated,
            workflow_run_url=request.workflow_run_url,
            collector_commit_sha=request.collector_commit_sha,
            candidates=(),
            failures=tuple(
                CollectionFailure(name=f"실패-{index}", stop_reason="test")
                for index in range(failed)
            ),
            stats=CollectionStats(
                sites_total=69,
                sites_succeeded=self.succeeded,
                total=0,
                candidates=0,
                engine_used=2,
            ),
        )

    def write(self, document: CandidateFile, output_dir: Path) -> Path:
        self.events.append("write")
        self.written = document
        if self.fail_write:
            message = "disk unavailable"
            raise OSError(message)
        return write_candidate_file(document, output_dir)


def test_below_threshold_still_writes_complete_file_and_summary(tmp_path: Path) -> None:
    harness = _Harness(root=tmp_path, succeeded=54)

    exit_code = run([], harness.dependencies())

    output_path = tmp_path / "data/candidates-2026-07-12.json"
    assert exit_code == 1
    assert harness.loaded_path == tmp_path / "korean_regional_newspapers.json"
    assert harness.request is not None
    assert harness.request.run_anchor == datetime(2026, 7, 12, 6, tzinfo=_KST)
    assert harness.request.run_date == date(2026, 7, 12)
    assert harness.request.workflow_run_url is None
    assert harness.events == ["clock", "sha", "registry", "collect", "clock", "write"]
    assert read_candidate_file(output_path) == harness.written
    summary = harness.stdout.getvalue()
    assert "총 기사 수: 0" in summary
    assert "후보 수: 0" in summary
    assert "엔진 폴백 수: 2" in summary
    assert "실패 사이트: 15" in summary
    assert "출력 경로: data/candidates-2026-07-12.json" in summary
    assert "69/69" in harness.stderr.getvalue()
    assert "example.com" not in harness.stderr.getvalue()


def test_threshold_success_and_complete_github_metadata(tmp_path: Path) -> None:
    environment = {
        "GITHUB_SERVER_URL": "https://github.com",
        "GITHUB_REPOSITORY": "owner/repo",
        "GITHUB_RUN_ID": "99",
        "GITHUB_SHA": "b" * 40,
    }
    harness = _Harness(root=tmp_path, environment=environment)

    assert run(["--date", "2026-07-12"], harness.dependencies()) == 0
    assert harness.request is not None
    assert harness.request.workflow_run_url == (
        "https://github.com/owner/repo/actions/runs/99"
    )
    assert harness.request.collector_commit_sha == "b" * 40
    assert "sha" not in harness.events


def test_stale_explicit_date_and_partial_github_env_are_config_errors(
    tmp_path: Path,
) -> None:
    stale = _Harness(root=tmp_path)
    with pytest.raises(SystemExit) as stale_exit:
        _ = run(["--date", "2026-07-11"], stale.dependencies())
    assert stale_exit.value.code == 2
    assert stale.events == ["clock"]

    partial = _Harness(
        root=tmp_path,
        environment={"GITHUB_SERVER_URL": "https://github.com"},
    )
    with pytest.raises(SystemExit) as partial_exit:
        _ = run([], partial.dependencies())
    assert partial_exit.value.code == 2
    assert partial.events == ["clock"]


def test_help_does_not_sample_time_or_touch_runtime(tmp_path: Path) -> None:
    harness = _Harness(root=tmp_path)

    with pytest.raises(SystemExit) as help_exit:
        _ = run(["--help"], harness.dependencies())

    assert help_exit.value.code == 0
    assert harness.events == []


def test_write_failure_is_fatal_and_reported(tmp_path: Path) -> None:
    harness = _Harness(root=tmp_path, fail_write=True)

    assert run([], harness.dependencies()) == 1
    assert "disk unavailable" in harness.stderr.getvalue()
