"""Typed runtime wiring for the daily regional-news collection command."""

import argparse
import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Final, Protocol, TextIO
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from scraper.collector import (
    CollectionProgress,
    CollectionRequest,
    CollectorDependencies,
    SiteFetcher,
    collect_candidates,
)
from scraper.fetching import SiteCollection, collect_site
from scraper.registry import NewspaperSource, RegistryError, load_registry
from scraper.schema import CandidateFile, write_candidate_file

_KST: Final = ZoneInfo("Asia/Seoul")
_SHA_PATTERN: Final = re.compile(r"^[0-9a-f]{40}$")
_REGISTRY_NAME: Final = "korean_regional_newspapers.json"


class ConfigurationError(ValueError):
    """A command input or environment cannot produce honest metadata."""


class Clock(Protocol):
    """Supply one wall-clock timestamp."""

    def __call__(self) -> datetime:
        """Return an aware timestamp."""
        ...


class RegistryLoader(Protocol):
    """Load immutable newspaper sources from one explicit path."""

    def __call__(self, path: Path) -> tuple[NewspaperSource, ...]:
        """Return validated sources."""
        ...


class CandidateCollector(Protocol):
    """Run the sequential collection boundary."""

    def __call__(
        self,
        sources: tuple[NewspaperSource, ...],
        request: CollectionRequest,
        dependencies: CollectorDependencies,
    ) -> CandidateFile:
        """Return one complete candidate handoff."""
        ...


class CandidateWriter(Protocol):
    """Persist one complete candidate handoff."""

    def __call__(self, document: CandidateFile, output_dir: Path) -> Path:
        """Return the final output path."""
        ...


class ShaFallback(Protocol):
    """Resolve the checked-out commit when Actions metadata is unavailable."""

    def __call__(self, repo_root: Path) -> str:
        """Return the current checked-out revision text."""
        ...


@dataclass(frozen=True, slots=True)
class RuntimeDependencies:
    """Injected local boundaries for a deterministic command run."""

    repo_root: Path
    environment: Mapping[str, str]
    clock: Clock
    registry_loader: RegistryLoader
    candidate_collector: CandidateCollector
    candidate_writer: CandidateWriter
    sha_fallback: ShaFallback
    site_fetcher: SiteFetcher
    stdout: TextIO
    stderr: TextIO


class _Arguments(argparse.Namespace):
    """Typed argparse destination container."""

    run_date_text: str | None

    def __init__(self) -> None:
        super().__init__()
        self.run_date_text = None


def workflow_run_url(environment: Mapping[str, str]) -> str | None:
    """Build the Actions run URL, rejecting incomplete environment metadata."""
    server = environment.get("GITHUB_SERVER_URL")
    repository = environment.get("GITHUB_REPOSITORY")
    run_id = environment.get("GITHUB_RUN_ID")
    if server is None and repository is None and run_id is None:
        return None
    if server is None or repository is None or run_id is None:
        message = (
            "GITHUB_SERVER_URL, GITHUB_REPOSITORY, and GITHUB_RUN_ID must all be set"
        )
        raise ConfigurationError(message)
    try:
        parsed_server = urlsplit(server)
    except ValueError as error:
        message = "GITHUB_SERVER_URL must be an HTTP(S) URL"
        raise ConfigurationError(message) from error
    if (
        parsed_server.scheme not in {"http", "https"}
        or parsed_server.netloc == ""
        or repository.strip() == ""
        or run_id.strip() == ""
    ):
        message = "GitHub workflow metadata contains an invalid value"
        raise ConfigurationError(message)
    return f"{server.rstrip('/')}/{repository}/actions/runs/{run_id}"


def collector_commit_sha(
    environment: Mapping[str, str],
    repo_root: Path,
    fallback: ShaFallback,
) -> str:
    """Prefer a valid Actions SHA, otherwise validate the checked-out revision."""
    github_sha = environment.get("GITHUB_SHA")
    if github_sha is not None and _SHA_PATTERN.fullmatch(github_sha) is not None:
        return github_sha
    fallback_sha = fallback(repo_root).strip()
    if _SHA_PATTERN.fullmatch(fallback_sha) is None:
        message = "collector commit SHA must be 40 lowercase hex digits"
        raise ConfigurationError(message)
    return fallback_sha


def _git_commit_sha(repo_root: Path) -> str:
    completed = subprocess.run(
        ["/usr/bin/git", "rev-parse", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        check=False,
        shell=False,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or "git rev-parse HEAD failed"
        raise ConfigurationError(detail)
    return completed.stdout


def _kst_now(clock: Clock) -> datetime:
    timestamp = clock()
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        message = "runtime clock must return an aware timestamp"
        raise ConfigurationError(message)
    return timestamp.astimezone(_KST)


def _fetch_site(homepage: str, run_day: date) -> SiteCollection:
    return collect_site(homepage, run_day)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="지역신문 기사 후보를 수집합니다.")
    _ = parser.add_argument(
        "--date",
        dest="run_date_text",
        metavar="YYYY-MM-DD",
        help="오늘의 KST 실행일(생략 시 현재 날짜)",
    )
    return parser


def _run_date(
    parser: argparse.ArgumentParser,
    requested: str | None,
    today: date,
) -> date:
    if requested is None:
        return today
    try:
        parsed = date.fromisoformat(requested)
    except ValueError:
        parser.error("--date must use YYYY-MM-DD format")
    if parsed != today:
        parser.error("--date must equal the current Asia/Seoul date")
    return parsed


def _progress(stream: TextIO, progress: CollectionProgress) -> None:
    message = (
        f"진행: {progress.sites_completed}/{progress.sites_total} "
        f"성공 {progress.sites_succeeded} 실패 {progress.sites_failed} "
        f"엔진 {progress.engine_used}"
    )
    print(
        message,
        file=stream,
        flush=True,
    )


def _summary(stream: TextIO, document: CandidateFile, path: Path) -> None:
    print(f"총 기사 수: {document.stats.total}", file=stream)
    print(f"후보 수: {document.stats.candidates}", file=stream)
    print(f"엔진 폴백 수: {document.stats.engine_used}", file=stream)
    print(f"실패 사이트: {len(document.failures)}", file=stream)
    print(f"출력 경로: {path}", file=stream, flush=True)


def run(argv: Sequence[str], dependencies: RuntimeDependencies) -> int:
    """Parse, collect, atomically write, summarize, and return readiness status."""
    parser = _parser()
    arguments = _Arguments()
    _ = parser.parse_args(argv, namespace=arguments)
    try:
        started_at = _kst_now(dependencies.clock)
        run_date = _run_date(parser, arguments.run_date_text, started_at.date())
        run_url = workflow_run_url(dependencies.environment)
        commit_sha = collector_commit_sha(
            dependencies.environment,
            dependencies.repo_root,
            dependencies.sha_fallback,
        )
        sources = dependencies.registry_loader(
            dependencies.repo_root / _REGISTRY_NAME,
        )
        document = dependencies.candidate_collector(
            sources,
            CollectionRequest(
                run_date=run_date,
                run_anchor=started_at,
                workflow_run_url=run_url,
                collector_commit_sha=commit_sha,
            ),
            CollectorDependencies(
                site_fetcher=dependencies.site_fetcher,
                generated_clock=lambda: _kst_now(dependencies.clock),
                observer=lambda progress: _progress(dependencies.stderr, progress),
            ),
        )
        output_path = dependencies.candidate_writer(
            document,
            dependencies.repo_root / "data",
        )
    except ConfigurationError as error:
        parser.error(str(error))
    except (OSError, RegistryError, ValidationError) as error:
        print(f"수집 실패: {error}", file=dependencies.stderr, flush=True)
        return 1

    _summary(
        dependencies.stdout,
        document,
        output_path.relative_to(dependencies.repo_root),
    )
    return 0 if document.meets_collection_threshold else 1


def _production_dependencies() -> RuntimeDependencies:
    return RuntimeDependencies(
        repo_root=Path(__file__).resolve().parents[1],
        environment=os.environ,
        clock=lambda: datetime.now(_KST),
        registry_loader=load_registry,
        candidate_collector=collect_candidates,
        candidate_writer=write_candidate_file,
        sha_fallback=_git_commit_sha,
        site_fetcher=_fetch_site,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the production command with optional explicit arguments."""
    arguments = sys.argv[1:] if argv is None else argv
    return run(arguments, _production_dependencies())


if __name__ == "__main__":
    raise SystemExit(main())
