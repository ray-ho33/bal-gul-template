"""Generic same-site URL and metadata-link safety predicates."""

import ipaddress
import re
from collections.abc import Iterator
from typing import Final
from urllib.parse import SplitResult, unquote, urljoin, urlsplit, urlunsplit

from bs4.element import Tag

MAX_DISCOVERED_FEEDS: Final = 3
MIN_ARTICLE_TITLE_LENGTH: Final = 6
_REGISTRABLE_LABEL_COUNT: Final = 2
_MOBILE_PREFIX_MIN_LABELS: Final = 2
_MOBILE_HOST_PREFIXES: Final = frozenset({"www", "m", "mobile"})
_KOREAN_SECOND_LEVEL_SUFFIXES: Final = frozenset(
    {"ac.kr", "co.kr", "go.kr", "ne.kr", "or.kr", "pe.kr", "re.kr"},
)
_FEED_LABEL: Final = re.compile(
    r"(?:^|[^a-z0-9])(?:atom|feeds?|rss\d*)(?:$|[^a-z0-9])|피드",
    re.IGNORECASE,
)
_ARTICLE_FAMILY: Final = re.compile(
    r"article|view|news|detail|read|story|body",
    re.IGNORECASE,
)
_NUMERIC_IDENTITY: Final = re.compile(r"(?<!\d)\d{4,}(?!\d)")
_NUMERIC_PATH: Final = re.compile(r"(?:^|/)\d{4,}(?:/|$)")
_EXCLUDED_ROUTE: Final = re.compile(
    r"""
    (?:assets?|category|list|login|media|nav|search|static)
    """,
    re.IGNORECASE | re.VERBOSE,
)
_NULL_ROUTE: Final = re.compile(
    r"(?:^|/)(?:null|undefined)(?:/|$)",
    re.IGNORECASE,
)
_ASSET_EXTENSION: Final = re.compile(
    r"""
    \.
    (?:avif|bmp|css|csv|gif|ico|jpe?g|js|json|mjs|mp3|mp4|pdf|png|svg|
       txt|webp|woff2?|xml|zip)
    $
    """,
    re.IGNORECASE | re.VERBOSE,
)
_META_REFRESH_URL: Final = re.compile(
    r"(?:^|;)\s*url\s*=\s*[\"']?([^\"';]+)",
    re.IGNORECASE,
)
_JS_LITERAL_URL: Final = re.compile(
    r"""
    (?:
      \b(?:document\.)?location(?:\.href)?\s*=\s*
      (?P<assign_quote>["'])(?P<assign>[^"']+)(?P=assign_quote)
    )
    |
    (?:
      \b(?:window\.)?location\.(?:assign|replace)\s*\(\s*
      (?P<call_quote>["'])(?P<call>[^"']+)(?P=call_quote)\s*\)
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)
_HIDDEN_STYLE: Final = re.compile(
    r"(?:display\s*:\s*none|visibility\s*:\s*hidden)",
    re.IGNORECASE,
)
_TRUE_VALUE: Final = re.compile(r"^true$", re.IGNORECASE)


def is_absolute_http_url(url: str) -> bool:
    """Return whether feed metadata contains a complete HTTP(S) URL."""
    return _http_parts(url) is not None


def safe_same_site_url(value: str, base_url: str) -> str | None:
    """Resolve, validate, same-site check, and remove a URL fragment."""
    raw = value.strip()
    if not raw or raw.startswith("#"):
        return None
    try:
        raw_scheme = urlsplit(raw).scheme.casefold()
        joined = urljoin(base_url, raw)
    except ValueError:
        return None
    if raw_scheme not in {"", "http", "https"}:
        return None
    parsed = _http_parts(joined)
    if parsed is None or not _same_site(base_url, joined):
        return None
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))


def advertises_feed(node: Tag) -> bool:
    """Return whether a link element explicitly advertises RSS or Atom."""
    if node.name.casefold() == "link":
        rel = {token.casefold() for token in node.get_attribute_list("rel")}
        media_type = attribute(node, "type").casefold()
        return "alternate" in rel and ("rss" in media_type or "atom" in media_type)
    label = " ".join(
        (attribute(node, "href"), attribute(node, "title"), node.get_text(" ")),
    )
    return _FEED_LABEL.search(label) is not None


def visible_anchor(node: Tag) -> bool:
    """Return whether an anchor exposes text rather than hidden metadata."""
    if node.has_attr("hidden") or attribute(node, "aria-hidden").casefold() == "true":
        return False
    if _HIDDEN_STYLE.search(attribute(node, "style")) is not None:
        return False
    hidden_parent = node.find_parent(attrs={"hidden": True})
    aria_hidden_parent = node.find_parent(attrs={"aria-hidden": _TRUE_VALUE})
    style_hidden_parent = node.find_parent(style=_HIDDEN_STYLE)
    return not any((hidden_parent, aria_hidden_parent, style_hidden_parent))


def is_article_url(url: str) -> bool:
    """Return whether a URL carries a stable numeric article identity."""
    parsed = _http_parts(url)
    if parsed is None:
        return False
    route = unquote(f"{parsed.path}?{parsed.query}")
    if _EXCLUDED_ROUTE.search(route) or _NULL_ROUTE.search(route):
        return False
    if _ASSET_EXTENSION.search(parsed.path):
        return False
    has_identity = _NUMERIC_IDENTITY.search(route) is not None
    has_family = _ARTICLE_FAMILY.search(route) is not None
    numeric_path = _NUMERIC_PATH.search(parsed.path) is not None
    return has_identity and (has_family or numeric_path)


def meta_handoff_candidate(node: Tag) -> str:
    """Extract a literal URL from recognized handoff metadata."""
    content = attribute(node, "content")
    label = (attribute(node, "property") or attribute(node, "name")).casefold()
    if label in {"og:url", "twitter:url"}:
        return content
    if attribute(node, "http-equiv").casefold() != "refresh":
        return ""
    match = _META_REFRESH_URL.search(content)
    return match.group(1).strip() if match is not None else ""


def literal_js_urls(html: str) -> Iterator[str]:
    """Yield only quoted URL literals from obvious redirect expressions."""
    for match in _JS_LITERAL_URL.finditer(html):
        yield match.group("assign") or match.group("call") or ""


def attribute(node: Tag, name: str) -> str:
    """Read a scalar BeautifulSoup attribute without untyped coercion."""
    value = node.get(name)
    return value.strip() if isinstance(value, str) else ""


def _same_site(first_url: str, second_url: str) -> bool:
    first = _http_parts(first_url)
    second = _http_parts(second_url)
    if first is None or second is None:
        return False
    first_host = first.hostname
    second_host = second.hostname
    return (
        first_host is not None
        and second_host is not None
        and _site_key(first_host.casefold()) == _site_key(second_host.casefold())
    )


def _http_parts(url: str) -> SplitResult | None:
    try:
        parsed = urlsplit(url)
        _ = parsed.port
    except ValueError:
        return None
    if parsed.scheme.casefold() not in {"http", "https"}:
        return None
    if (
        parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    return parsed


def _site_key(host: str) -> str:
    normalized = host.rstrip(".")
    try:
        return str(ipaddress.ip_address(normalized))
    except ValueError:
        labels = normalized.split(".")
    while (
        len(labels) >= _MOBILE_PREFIX_MIN_LABELS and labels[0] in _MOBILE_HOST_PREFIXES
    ):
        _ = labels.pop(0)
    if len(labels) <= _REGISTRABLE_LABEL_COUNT:
        return ".".join(labels)
    tail = ".".join(labels[-_REGISTRABLE_LABEL_COUNT:])
    suffix_labels = _REGISTRABLE_LABEL_COUNT + 1
    return (
        ".".join(labels[-suffix_labels:])
        if tail in _KOREAN_SECOND_LEVEL_SUFFIXES
        else tail
    )
