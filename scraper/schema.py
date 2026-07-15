"""Strict JSON handoff schema for daily article candidates."""

import os
from dataclasses import dataclass
from datetime import date, timedelta, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Annotated, ClassVar, Final, Literal, LiteralString, Self, TypeAlias
from urllib.parse import urlsplit

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)
from pydantic_core import PydanticCustomError
from typing_extensions import override

from scraper.filtering import KeywordHits

CollectionMethod: TypeAlias = Literal["requests", "engine"]
NonBlankText: TypeAlias = Annotated[
    str,
    StringConstraints(min_length=1, pattern=r"\S"),
]
CommitSha: TypeAlias = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9a-f]{40}$"),
]
NonNegativeInt: TypeAlias = Annotated[int, Field(ge=0)]
SiteCount: TypeAlias = Annotated[int, Field(ge=0, le=88)]

_KST: Final = timezone(timedelta(hours=9))
_SITE_TOTAL: Final = 88
_READINESS_THRESHOLD: Final = 55


def _schema_error(
    code: LiteralString,
    message: LiteralString,
) -> PydanticCustomError:
    return PydanticCustomError(code, message)


def _require_http_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
    except ValueError as error:
        validation_error = _schema_error(
            "http_url",
            "must be an absolute HTTP(S) URL",
        )
        raise validation_error from error
    if parsed.scheme not in {"http", "https"} or hostname is None:
        validation_error = _schema_error(
            "http_url",
            "must be an absolute HTTP(S) URL",
        )
        raise validation_error
    return value


HttpUrlString: TypeAlias = Annotated[str, AfterValidator(_require_http_url)]


class CandidateKeywordHits(BaseModel):
    """Matched youth and hardship terms with Korean JSON keys."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        validate_by_alias=True,
        validate_by_name=True,
    )

    youth_terms: Annotated[tuple[NonBlankText, ...], Field(min_length=1)] = Field(
        alias="청년",
    )
    hardship_terms: Annotated[tuple[NonBlankText, ...], Field(min_length=1)] = Field(
        alias="고충",
    )

    @classmethod
    def from_keyword_hits(cls, hits: KeywordHits) -> Self:
        """Parse filtering results into the serialized handoff value."""
        return cls.model_validate(
            {"청년": hits.youth_terms, "고충": hits.hardship_terms},
        )

    @model_validator(mode="after")
    def require_unique_terms(self) -> Self:
        """Reject repeated terms within either keyword group."""
        if len(set(self.youth_terms)) != len(self.youth_terms):
            validation_error = _schema_error(
                "duplicate_keyword",
                "youth keyword terms must be unique",
            )
            raise validation_error
        if len(set(self.hardship_terms)) != len(self.hardship_terms):
            validation_error = _schema_error(
                "duplicate_keyword",
                "hardship keyword terms must be unique",
            )
            raise validation_error
        return self


class ArticleCandidate(BaseModel):
    """One recent article that passed the deterministic keyword filter."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )

    newspaper_name: NonBlankText
    region: NonBlankText
    title: NonBlankText
    link: HttpUrlString
    summary: str = ""
    published: AwareDatetime
    method: CollectionMethod
    keyword_hits: CandidateKeywordHits


class CollectionFailure(BaseModel):
    """A newspaper that could not be collected, with engine stop context."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )

    name: NonBlankText
    stop_reason: NonBlankText


class CollectionStats(BaseModel):
    """Aggregate counts for the 88-site collection run."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )

    sites_total: Literal[88]
    sites_succeeded: SiteCount
    total: NonNegativeInt
    candidates: NonNegativeInt
    engine_used: SiteCount

    @model_validator(mode="after")
    def require_consistent_counts(self) -> Self:
        """Keep the candidate count within the total article count."""
        if self.candidates > self.total:
            validation_error = _schema_error(
                "candidate_count",
                "candidate count cannot exceed total article count",
            )
            raise validation_error
        return self


class CandidateFile(BaseModel):
    """Complete file contract passed from collection to Codex reporting."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )

    run_date: date
    generated_at: AwareDatetime
    workflow_run_url: HttpUrlString | None
    collector_commit_sha: CommitSha
    candidates: tuple[ArticleCandidate, ...]
    failures: tuple[CollectionFailure, ...]
    stats: CollectionStats

    @property
    def meets_collection_threshold(self) -> bool:
        """Return whether at least 55 newspapers succeeded, even with no articles."""
        return self.stats.sites_succeeded >= _READINESS_THRESHOLD

    @model_validator(mode="after")
    def require_coherent_handoff(self) -> Self:
        """Validate cross-record counts, dates, and identifiers."""
        if self.generated_at.astimezone(_KST).date() != self.run_date:
            validation_error = _schema_error(
                "generated_date",
                "generated_at KST date must equal run_date",
            )
            raise validation_error
        if self.stats.candidates != len(self.candidates):
            validation_error = _schema_error(
                "candidate_count",
                "stats candidates must equal candidate tuple length",
            )
            raise validation_error
        if self.stats.sites_succeeded + len(self.failures) != _SITE_TOTAL:
            validation_error = _schema_error(
                "site_accounting",
                "succeeded sites and failures must account for 88 sites",
            )
            raise validation_error
        failure_names = tuple(failure.name for failure in self.failures)
        if len(set(failure_names)) != len(failure_names):
            validation_error = _schema_error(
                "duplicate_failure",
                "failure names must be unique",
            )
            raise validation_error
        candidate_links = tuple(candidate.link for candidate in self.candidates)
        if len(set(candidate_links)) != len(candidate_links):
            validation_error = _schema_error(
                "duplicate_candidate",
                "candidate links must be unique",
            )
            raise validation_error
        return self


@dataclass(frozen=True, slots=True)
class CandidateFilenameError(Exception):
    """A candidate document's filename does not match its run date."""

    path: Path
    expected_name: str

    @override
    def __str__(self) -> str:
        """Describe the expected dated filename."""
        return f"{self.path.name!r} must be named {self.expected_name!r}"


def write_candidate_file(document: CandidateFile, output_dir: Path) -> Path:
    """Atomically write the dated candidate JSON document with a final newline."""
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"candidates-{document.run_date.isoformat()}.json"
    encoded = document.model_dump_json(by_alias=True, indent=2) + "\n"
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output_dir,
            prefix=f".{target.name}.",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            _ = temporary_file.write(encoded)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        _ = temporary_path.replace(target)
    except OSError:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise
    return target


def read_candidate_file(path: Path) -> CandidateFile:
    """Parse a candidate JSON file and enforce its dated filename contract."""
    document = CandidateFile.model_validate_json(path.read_text(encoding="utf-8"))
    expected_name = f"candidates-{document.run_date.isoformat()}.json"
    if path.name != expected_name:
        raise CandidateFilenameError(path=path, expected_name=expected_name)
    return document
