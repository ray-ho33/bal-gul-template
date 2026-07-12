"""Runtime requests and vendored-engine adapters for typed site fetching."""

import codecs
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol, TypedDict, Unpack

import requests

from scraper.schema import CollectionMethod

_STREAM_CHUNK_BYTES: Final = 64 * 1024
_META_SCAN_BYTES: Final = 16 * 1024
_META_TAG_PATTERN: Final = re.compile(rb"<meta\b[^>]{0,512}>", re.IGNORECASE)
_CHARSET_PATTERN: Final = re.compile(
    rb"\bcharset\s*=\s*[\"']?\s*([a-zA-Z0-9._-]+)",
    re.IGNORECASE,
)


class _EngineResult(Protocol):
    ok: bool
    content: str
    final_url: str
    stop_reason: str


class _EngineOptions(TypedDict):
    timeout: int
    max_attempts: int
    enable_playwright: bool
    enable_phase0: bool
    enable_learning: bool


class _EngineFetch(Protocol):
    def __call__(
        self, url: str, **options: Unpack[_EngineOptions]
    ) -> _EngineResult: ...


if TYPE_CHECKING:
    engine_fetch: _EngineFetch
else:
    from vendor.engine import fetch as engine_fetch


@dataclass(frozen=True, slots=True)
class HttpRequest:
    """Bounded request passed to the HTTP transport."""

    url: str
    headers: tuple[tuple[str, str], ...]
    timeout_seconds: float
    follow_redirects: bool
    max_bytes: int


@dataclass(frozen=True, slots=True)
class HttpDocument:
    """Bounded HTTP response returned by the transport."""

    status_code: int
    content: bytes
    final_url: str
    encoding: str | None = None


@dataclass(frozen=True, slots=True)
class EngineRequest:
    """Cloud-safe engine request with executable phases disabled."""

    url: str
    timeout_seconds: int = 10
    max_attempts: int = 3
    max_bytes: int = 2 * 1024 * 1024
    enable_playwright: bool = False
    enable_phase0: bool = False
    enable_learning: bool = False


@dataclass(frozen=True, slots=True)
class EngineDocument:
    """Static text result returned by the vendored engine adapter."""

    ok: bool
    content: str
    final_url: str
    stop_reason: str


@dataclass(frozen=True, slots=True)
class FetchTransportError(Exception):
    """An expected HTTP or engine transport operation failed."""

    url: str
    method: CollectionMethod
    detail: str

    def __post_init__(self) -> None:
        """Initialize the exception message from bounded typed fields."""
        Exception.__init__(
            self,
            f"{self.method} transport failed for {self.url}: {self.detail}",
        )


class DocumentGetter(Protocol):
    """Execute one bounded HTTP request."""

    def __call__(self, request: HttpRequest) -> HttpDocument:
        """Return a bounded response document."""
        ...


class EngineGetter(Protocol):
    """Execute one cloud-safe vendored-engine request."""

    def __call__(self, request: EngineRequest) -> EngineDocument:
        """Return static engine output only."""
        ...


class Sleeper(Protocol):
    """Apply the explicit inter-request pacing delay."""

    def __call__(self, seconds: float, /) -> None:
        """Wait for the requested pacing interval."""
        ...


@dataclass(frozen=True, slots=True)
class FetchDependencies:
    """Injected HTTP, engine, and pacing boundaries."""

    document_getter: DocumentGetter
    engine_getter: EngineGetter
    sleeper: Sleeper


def decode_html_document(document: HttpDocument) -> str:
    """Decode HTML by valid meta charset, then strict UTF-8 and CP949 fallback."""
    prefix = document.content[:_META_SCAN_BYTES]
    for tag_match in _META_TAG_PATTERN.finditer(prefix):
        charset_match = _CHARSET_PATTERN.search(tag_match.group())
        if charset_match is None:
            continue
        label = charset_match.group(1).decode("ascii")
        try:
            codec = codecs.lookup(label)
        except LookupError:
            continue
        return document.content.decode(codec.name, errors="replace")
    try:
        return document.content.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return document.content.decode("cp949")
        except UnicodeDecodeError:
            return document.content.decode("cp949", errors="replace")


def get_http_document(request: HttpRequest) -> HttpDocument:
    """Stream one requests response without retaining bytes beyond its cap."""
    try:
        response = requests.get(
            request.url,
            headers=dict(request.headers),
            timeout=request.timeout_seconds,
            allow_redirects=request.follow_redirects,
            stream=True,
        )
        with response:
            content = bytearray()
            for chunk in response.iter_content(chunk_size=_STREAM_CHUNK_BYTES):
                if not chunk:
                    continue
                if len(content) + len(chunk) > request.max_bytes:
                    detail = f"response exceeds {request.max_bytes} bytes"
                    raise FetchTransportError(
                        url=request.url,
                        method="requests",
                        detail=detail,
                    )
                content.extend(chunk)
            return HttpDocument(
                status_code=response.status_code,
                content=bytes(content),
                final_url=response.url,
                encoding=response.encoding,
            )
    except requests.RequestException as error:
        detail = str(error) or type(error).__name__
        raise FetchTransportError(
            url=request.url,
            method="requests",
            detail=detail,
        ) from error


def get_engine_document(request: EngineRequest) -> EngineDocument:
    """Run the vendored engine with every executable cloud phase disabled."""
    try:
        result = engine_fetch(
            request.url,
            timeout=request.timeout_seconds,
            max_attempts=request.max_attempts,
            enable_playwright=request.enable_playwright,
            enable_phase0=request.enable_phase0,
            enable_learning=request.enable_learning,
        )
    except (OSError, RuntimeError, ValueError) as error:
        detail = str(error) or type(error).__name__
        raise FetchTransportError(
            url=request.url,
            method="engine",
            detail=detail,
        ) from error
    if len(result.content.encode("utf-8")) > request.max_bytes:
        detail = f"response exceeds {request.max_bytes} bytes"
        raise FetchTransportError(
            url=request.url,
            method="engine",
            detail=detail,
        )
    return EngineDocument(
        ok=result.ok,
        content=result.content,
        final_url=result.final_url,
        stop_reason=result.stop_reason,
    )


DEFAULT_FETCH_DEPENDENCIES: Final = FetchDependencies(
    document_getter=get_http_document,
    engine_getter=get_engine_document,
    sleeper=time.sleep,
)


__all__: Final = (
    "DEFAULT_FETCH_DEPENDENCIES",
    "DocumentGetter",
    "EngineDocument",
    "EngineGetter",
    "EngineRequest",
    "FetchDependencies",
    "FetchTransportError",
    "HttpDocument",
    "HttpRequest",
    "Sleeper",
    "decode_html_document",
    "get_engine_document",
    "get_http_document",
)
