"""Pure metadata parsers for feeds and newspaper homepages."""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import StrEnum
from typing import Final
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup
from bs4.element import Tag

from scraper.filtering import CurrentDayPublication, parse_rss_timestamp
from scraper.url_safety import (
    MAX_DISCOVERED_FEEDS,
    MIN_ARTICLE_TITLE_LENGTH,
    advertises_feed,
    attribute,
    is_absolute_http_url,
    is_article_url,
    literal_js_urls,
    meta_handoff_candidate,
    safe_same_site_url,
    visible_anchor,
)

_KST: Final = timezone(timedelta(hours=9))
_MAX_HOMEPAGE_TITLE_LENGTH: Final = 200
_MAX_PUBLICATION_ANCESTORS: Final = 6
_DATE_ATTRIBUTE_NAMES: Final = frozenset(
    {
        "date",
        "datetime",
        "data-date",
        "data-datetime",
        "data-pubdate",
        "data-published",
        "data-created",
        "data-time",
    },
)
_DATE_LABEL: Final = re.compile(
    r"(?:^|[-_])(?:created|date|datetime|pubdate|published?|time|등록일|작성일)(?:$|[-_])",
    re.IGNORECASE,
)
_SEPARATED_DATE: Final = re.compile(
    r"""(?<!\d)(?P<year>20\d{2})[./_-](?P<month>0?[1-9]|1[0-2])
    [./_-](?P<day>0?[1-9]|[12]\d|3[01])(?!\d)""",
    re.VERBOSE,
)
_COMPACT_DATE: Final = re.compile(
    r"""(?<!\d)(?P<year>20\d{2})(?P<month>0[1-9]|1[0-2])
    (?P<day>0[1-9]|[12]\d|3[01])(?!\d)""",
    re.VERBOSE,
)


@dataclass(frozen=True, slots=True)
class RawArticle:
    """Immutable title-and-summary metadata collected before filtering."""

    title: str
    link: str
    summary: str
    published: datetime | CurrentDayPublication


@dataclass(frozen=True, slots=True)
class _PublicationEvidence:
    """One explicit publication date, optionally retaining its exact time."""

    day: date
    timestamp: datetime | None = None


class FeedParseReason(StrEnum):
    """Machine-readable reasons a feed payload was unusable."""

    EMPTY = "empty"
    HTML = "html"
    MALFORMED_XML = "malformed_xml"
    ZERO_VALID_ITEMS = "zero_valid_items"


class FeedParseError(ValueError):
    """A whole feed payload could not produce article metadata."""

    reason: FeedParseReason

    def __init__(self, reason: FeedParseReason) -> None:
        """Initialize an error with its stable machine-readable reason."""
        self.reason = reason
        super().__init__(f"feed payload rejected: {reason.value}")


def parse_feed(content: bytes) -> tuple[RawArticle, ...]:
    """Parse namespace-tolerant RSS or Atom bytes without fetching links."""
    stripped = content.strip()
    if not stripped:
        raise FeedParseError(FeedParseReason.EMPTY)
    if _looks_like_html(stripped):
        raise FeedParseError(FeedParseReason.HTML)

    try:
        root = _parse_xml(content)
    except ET.ParseError as error:
        raise FeedParseError(FeedParseReason.MALFORMED_XML) from error
    if _local_name(root.tag) == "html":
        raise FeedParseError(FeedParseReason.HTML)

    articles = tuple(
        article
        for element in root.iter()
        if _local_name(element.tag) in {"entry", "item"}
        if (article := _parse_feed_item(element)) is not None
    )
    if not articles:
        raise FeedParseError(FeedParseReason.ZERO_VALID_ITEMS)
    return articles


def discover_feed_urls(
    html: str,
    base_url: str,
    limit: int = MAX_DISCOVERED_FEEDS,
) -> tuple[str, ...]:
    """Return up to three advertised same-site HTTP feed URLs."""
    capacity = min(max(limit, 0), MAX_DISCOVERED_FEEDS)
    if capacity == 0 or not is_absolute_http_url(base_url):
        return ()

    discovered: list[str] = []
    for node in BeautifulSoup(html, "html.parser").find_all(["link", "a"]):
        if not advertises_feed(node):
            continue
        candidate = safe_same_site_url(attribute(node, "href"), base_url)
        if candidate is not None and candidate not in discovered:
            discovered.append(candidate)
        if len(discovered) == capacity:
            break
    return tuple(discovered)


def parse_homepage_articles(
    html: str,
    base_url: str,
    run_day: date,
) -> tuple[RawArticle, ...]:
    """Extract plausible explicitly dated article metadata from visible anchors."""
    if not is_absolute_http_url(base_url):
        return ()

    articles: list[RawArticle] = []
    seen: set[str] = set()
    for node in BeautifulSoup(html, "html.parser").find_all("a"):
        anchor = _homepage_anchor(node, base_url)
        if anchor is None:
            continue
        title, link = anchor
        if link in seen:
            continue
        published = _homepage_publication(node, link, base_url, run_day)
        if published is None:
            continue
        seen.add(link)
        articles.append(
            RawArticle(
                title=title,
                link=link,
                summary="",
                published=published,
            ),
        )
    return tuple(articles)


def homepage_has_article_anchors(html: str, base_url: str) -> bool:
    """Return whether accessible HTML exposes plausible bounded article links."""
    if not is_absolute_http_url(base_url):
        return False
    return any(
        _homepage_anchor(node, base_url) is not None
        for node in BeautifulSoup(html, "html.parser").find_all("a")
    )


def reported_handoff_url(html: str, base_url: str) -> str | None:
    """Report one literal same-site handoff target without following it."""
    if not is_absolute_http_url(base_url):
        return None
    soup = BeautifulSoup(html, "html.parser")
    for node in soup.find_all("meta"):
        safe_url = safe_same_site_url(meta_handoff_candidate(node), base_url)
        if safe_url is not None:
            return safe_url
    for candidate in literal_js_urls(html):
        safe_url = safe_same_site_url(candidate, base_url)
        if safe_url is not None:
            return safe_url
    return None


def _parse_xml(content: bytes) -> ET.Element:
    lowered = content.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise FeedParseError(FeedParseReason.MALFORMED_XML)
    return ET.XML(content)


def _parse_feed_item(element: ET.Element) -> RawArticle | None:
    title = _field_text(element, ("title",))
    link = _feed_link(element)
    timestamp = _field_text(element, ("pubdate", "published", "updated"))
    if not title or not link or not timestamp:
        return None
    try:
        published = parse_rss_timestamp(timestamp)
    except ValueError:
        return None
    return RawArticle(
        title=title,
        link=link,
        summary=_field_text(element, ("description", "summary")),
        published=published,
    )


def _feed_link(element: ET.Element) -> str:
    links = tuple(child for child in element if _local_name(child.tag) == "link")
    preferred = tuple(
        child
        for child in links
        if child.attrib.get("rel", "").casefold() in {"", "alternate"}
    )
    for child in preferred + links:
        link = child.attrib.get("href", "").strip() or _element_text(child)
        if is_absolute_http_url(link):
            return link
    return ""


def _field_text(element: ET.Element, names: tuple[str, ...]) -> str:
    for name in names:
        for child in element:
            if _local_name(child.tag) == name:
                text = _element_text(child)
                if text:
                    return text
    return ""


def _element_text(element: ET.Element) -> str:
    return _normalise_text("".join(element.itertext()))


def _normalise_text(value: str) -> str:
    return " ".join(value.split())


def _homepage_title(node: Tag) -> str:
    """Read one bounded headline without promoting an anchor body to a title."""
    candidates = (
        *(
            heading.get_text(" ", strip=True)
            for heading in node.find_all(("h1", "h2", "h3", "h4", "h5", "h6"))
        ),
        attribute(node, "aria-label"),
        attribute(node, "title"),
        attribute(node, "data-title"),
        *(attribute(image, "alt") for image in node.find_all("img")),
        node.get_text(" ", strip=True),
    )
    for value in candidates:
        title = _normalise_text(value)
        if MIN_ARTICLE_TITLE_LENGTH <= len(title) <= _MAX_HOMEPAGE_TITLE_LENGTH:
            return title
    return ""


def _homepage_anchor(node: Tag, base_url: str) -> tuple[str, str] | None:
    if not visible_anchor(node):
        return None
    title = _homepage_title(node)
    link = safe_same_site_url(attribute(node, "href"), base_url)
    if not title or link is None or not is_article_url(link):
        return None
    return title, link


def _homepage_publication(
    node: Tag,
    link: str,
    base_url: str,
    run_day: date,
) -> datetime | CurrentDayPublication | None:
    """Require article-local, explicit run-day evidence for homepage metadata."""
    parsed_link = urlsplit(link)
    link_evidence = _publication_evidence(
        unquote(f"{parsed_link.path}?{parsed_link.query}"),
    )
    if link_evidence:
        return _resolve_publication(link_evidence, run_day)

    direct_evidence = _metadata_publication_evidence(node)
    if direct_evidence:
        return _resolve_publication(direct_evidence, run_day)

    for depth, ancestor in enumerate(node.parents, start=1):
        if depth > _MAX_PUBLICATION_ANCESTORS:
            break
        if ancestor.name.casefold() in {"body", "html"}:
            break
        if not _contains_only_article_target(ancestor, link, base_url):
            continue
        local_evidence = _metadata_publication_evidence(ancestor)
        if local_evidence:
            return _resolve_publication(local_evidence, run_day)
    return None


def _contains_only_article_target(container: Tag, link: str, base_url: str) -> bool:
    targets = {
        candidate
        for anchor in container.find_all("a")
        if visible_anchor(anchor)
        if (candidate := safe_same_site_url(attribute(anchor, "href"), base_url))
        is not None
        if is_article_url(candidate)
    }
    return targets == {link}


def _metadata_publication_evidence(
    root: Tag,
) -> tuple[_PublicationEvidence, ...]:
    values: list[str] = []
    elements = (root, *root.find_all())
    for element in elements:
        if element.name.casefold() == "time":
            values.extend(
                (
                    attribute(element, "datetime"),
                    attribute(element, "content"),
                    element.get_text(" ", strip=True),
                ),
            )
        values.extend(attribute(element, name) for name in _DATE_ATTRIBUTE_NAMES)
        itemprop = attribute(element, "itemprop")
        if itemprop.casefold() in {"datecreated", "datemodified", "datepublished"}:
            values.extend(
                (
                    attribute(element, "content"),
                    attribute(element, "datetime"),
                    element.get_text(" ", strip=True),
                ),
            )
        labels = _attribute_tokens(element, "class") + _attribute_tokens(element, "id")
        if any(_DATE_LABEL.search(label) is not None for label in labels):
            values.append(element.get_text(" ", strip=True))

    return tuple(
        evidence
        for value in values
        if value
        for evidence in _publication_evidence(value)
    )


def _attribute_tokens(node: Tag, name: str) -> tuple[str, ...]:
    value = node.get(name)
    if isinstance(value, str):
        return tuple(value.split())
    if isinstance(value, list):
        return tuple(value)
    return ()


def _publication_evidence(value: str) -> tuple[_PublicationEvidence, ...]:
    raw = _normalise_text(value)
    if not raw:
        return ()

    exact = _exact_publication_evidence(raw)
    if exact is not None:
        return (exact,)

    return _pattern_publication_evidence(raw)


def _exact_publication_evidence(raw: str) -> _PublicationEvidence | None:
    try:
        exact_day = date.fromisoformat(raw)
    except ValueError:
        pass
    else:
        return _PublicationEvidence(exact_day)

    try:
        timestamp = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        timestamp = timestamp.replace(tzinfo=_KST)
    return _PublicationEvidence(timestamp.astimezone(_KST).date(), timestamp)


def _pattern_publication_evidence(raw: str) -> tuple[_PublicationEvidence, ...]:
    evidence: list[_PublicationEvidence] = []
    for pattern in (_SEPARATED_DATE, _COMPACT_DATE):
        for match in pattern.finditer(raw):
            try:
                matched_day = date(
                    int(match.group("year")),
                    int(match.group("month")),
                    int(match.group("day")),
                )
            except ValueError:
                continue
            item = _PublicationEvidence(matched_day)
            if item not in evidence:
                evidence.append(item)
    return tuple(evidence)


def _resolve_publication(
    evidence: tuple[_PublicationEvidence, ...],
    run_day: date,
) -> datetime | CurrentDayPublication | None:
    days = {item.day for item in evidence}
    if len(days) != 1:
        return None
    publication_day = next(iter(days))
    if publication_day > run_day:
        return None
    exact_timestamp = next(
        (item.timestamp for item in evidence if item.timestamp is not None),
        None,
    )
    return exact_timestamp or CurrentDayPublication(publication_day)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _looks_like_html(content: bytes) -> bool:
    prefix = content.lstrip(b"\xef\xbb\xbf\t\r\n ").lower()[:256]
    return prefix.startswith((b"<!doctype html", b"<html"))


__all__: Final = (
    "FeedParseError",
    "FeedParseReason",
    "RawArticle",
    "discover_feed_urls",
    "homepage_has_article_anchors",
    "parse_feed",
    "parse_homepage_articles",
    "reported_handoff_url",
)
