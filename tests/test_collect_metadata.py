from pathlib import Path
from typing import final

import pytest
from scraper.collect_runtime import (
    ConfigurationError,
    collector_commit_sha,
    workflow_run_url,
)


@final
class _ShaFallback:
    __slots__ = ("calls", "value")

    def __init__(self, value: str) -> None:
        self.value = value
        self.calls = 0

    def __call__(self, repo_root: Path) -> str:
        assert repo_root == Path.cwd()
        self.calls += 1
        return self.value


def test_workflow_url_is_none_only_when_all_github_fields_are_absent() -> None:
    assert workflow_run_url({}) is None

    with pytest.raises(ConfigurationError, match="all be set"):
        _ = workflow_run_url({"GITHUB_SERVER_URL": "https://github.com"})


def test_workflow_url_uses_complete_github_actions_environment() -> None:
    environment = {
        "GITHUB_SERVER_URL": "https://github.example/",
        "GITHUB_REPOSITORY": "owner/private-repo",
        "GITHUB_RUN_ID": "12345",
    }

    assert workflow_run_url(environment) == (
        "https://github.example/owner/private-repo/actions/runs/12345"
    )


def test_valid_github_sha_bypasses_git_fallback() -> None:
    fallback = _ShaFallback("b" * 40)

    resolved = collector_commit_sha(
        {"GITHUB_SHA": "a" * 40},
        Path.cwd(),
        fallback,
    )

    assert resolved == "a" * 40
    assert fallback.calls == 0


def test_invalid_github_sha_falls_back_and_validates_git_sha() -> None:
    fallback = _ShaFallback("b" * 40)

    resolved = collector_commit_sha(
        {"GITHUB_SHA": "A" * 40},
        Path.cwd(),
        fallback,
    )

    assert resolved == "b" * 40
    assert fallback.calls == 1

    with pytest.raises(ConfigurationError, match="40 lowercase"):
        _ = collector_commit_sha({}, Path.cwd(), _ShaFallback("not-a-sha"))
