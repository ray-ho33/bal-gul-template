"""Strict parsing for the nested regional-newspaper registry."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Annotated, ClassVar, Final, Literal, TypeAlias

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    HttpUrl,
    TypeAdapter,
    ValidationError,
)
from pydantic_core import PydanticCustomError

EXPECTED_REGION_COUNT: Final = 6
EXPECTED_SOURCE_COUNT: Final = 69


def _require_non_blank(value: str) -> str:
    if not value.strip():
        error_code = "blank_text"
        message = "Input must not be blank"
        raise PydanticCustomError(error_code, message)
    if value != value.strip():
        error_code = "surrounding_whitespace"
        message = "Input must not contain surrounding whitespace"
        raise PydanticCustomError(error_code, message)
    return value


_NonBlankText: TypeAlias = Annotated[str, AfterValidator(_require_non_blank)]
_HTTP_URL_ADAPTER: Final[TypeAdapter[HttpUrl]] = TypeAdapter(
    HttpUrl,
    config=ConfigDict(strict=True),
)


def _require_http_url(value: str) -> str:
    _ = _HTTP_URL_ADAPTER.validate_python(value)
    return value


_HttpUrlText: TypeAlias = Annotated[
    _NonBlankText,
    AfterValidator(_require_http_url),
]


class NewspaperSource(BaseModel):
    """A validated newspaper with its parent registry region injected."""

    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )

    name: _NonBlankText
    region: _NonBlankText
    homepage: _HttpUrlText
    namu_wiki: _HttpUrlText | None = None


class _NestedSource(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )

    name: _NonBlankText
    homepage: _HttpUrlText
    namu_wiki: _HttpUrlText | None = None


class _RegistryEnvelope(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )

    source: _NonBlankText
    retrieved: date
    regions: dict[_NonBlankText, tuple[_NestedSource, ...]]


class RegistryError(Exception):
    """Base class for typed registry-boundary failures."""


@dataclass(frozen=True, slots=True)
class RegistryReadError(RegistryError):
    """A registry path could not be read."""

    path: Path
    detail: str

    def __post_init__(self) -> None:
        """Initialize the exception message from the typed fields."""
        RegistryError.__init__(
            self,
            f"could not read registry {self.path}: {self.detail}",
        )


@dataclass(frozen=True, slots=True)
class RegistrySchemaError(RegistryError):
    """Registry JSON did not match the strict nested schema."""

    detail: str

    def __post_init__(self) -> None:
        """Initialize the exception message from the typed field."""
        RegistryError.__init__(
            self,
            f"registry schema validation failed: {self.detail}",
        )


@dataclass(frozen=True, slots=True)
class DuplicateSourceError(RegistryError):
    """Two nested sources shared a unique identity field."""

    field: Literal["name", "homepage"]
    value: str

    def __post_init__(self) -> None:
        """Initialize the exception message from the typed fields."""
        RegistryError.__init__(
            self,
            f"duplicate registry {self.field}: {self.value!r}",
        )


@dataclass(frozen=True, slots=True)
class RegistryCountError(RegistryError):
    """Registry region or source cardinality was not exact."""

    scope: Literal["regions", "sources"]
    expected: int
    actual: int

    def __post_init__(self) -> None:
        """Initialize the exception message from the typed fields."""
        RegistryError.__init__(
            self,
            (f"registry {self.scope} count must be {self.expected}, got {self.actual}"),
        )


def parse_registry_json(raw: str | bytes) -> tuple[NewspaperSource, ...]:
    """Parse a registry JSON blob into a validated immutable source tuple."""
    try:
        envelope = _RegistryEnvelope.model_validate_json(raw)
    except ValidationError as error:
        raise RegistrySchemaError(detail=str(error)) from error

    sources: list[NewspaperSource] = []
    names: set[str] = set()
    homepages: set[str] = set()
    for region, nested_sources in envelope.regions.items():
        for nested in nested_sources:
            if nested.name in names:
                raise DuplicateSourceError(field="name", value=nested.name)
            if nested.homepage in homepages:
                raise DuplicateSourceError(
                    field="homepage",
                    value=nested.homepage,
                )
            names.add(nested.name)
            homepages.add(nested.homepage)
            sources.append(
                NewspaperSource(
                    name=nested.name,
                    region=region,
                    homepage=nested.homepage,
                    namu_wiki=nested.namu_wiki,
                ),
            )

    if len(envelope.regions) != EXPECTED_REGION_COUNT:
        raise RegistryCountError(
            scope="regions",
            expected=EXPECTED_REGION_COUNT,
            actual=len(envelope.regions),
        )
    if len(sources) != EXPECTED_SOURCE_COUNT:
        raise RegistryCountError(
            scope="sources",
            expected=EXPECTED_SOURCE_COUNT,
            actual=len(sources),
        )
    return tuple(sources)


def load_registry(path: Path) -> tuple[NewspaperSource, ...]:
    """Read and parse a registry from an explicit filesystem path."""
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise RegistryReadError(path=path, detail=str(error)) from error
    return parse_registry_json(raw)


__all__: Final = (
    "EXPECTED_REGION_COUNT",
    "EXPECTED_SOURCE_COUNT",
    "DuplicateSourceError",
    "NewspaperSource",
    "RegistryCountError",
    "RegistryError",
    "RegistryReadError",
    "RegistrySchemaError",
    "load_registry",
    "parse_registry_json",
)
