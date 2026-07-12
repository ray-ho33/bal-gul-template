from dataclasses import FrozenInstanceError
from datetime import date, datetime, timedelta

import pytest
from scraper.filtering import CurrentDayPublication
from scraper.parsing import (
    FeedParseError,
    FeedParseReason,
    RawArticle,
    discover_feed_urls,
    parse_feed,
    parse_homepage_articles,
    reported_handoff_url,
)


def test_rss_parses_rfc_timestamp_cdata_and_skips_bad_items() -> None:
    content = b"""<?xml version="1.0" encoding="UTF-8"?>
    <rss><channel>
      <item><title><![CDATA[Residents challenge a permit]]></title>
        <link>https://press.test/article/view?item=12001</link>
        <description><![CDATA[Council response & public comment]]></description>
        <pubDate>Sun, 12 Jul 2026 05:30:00 +0900</pubDate></item>
      <item><title>Summary is optional here</title>
        <link>https://press.test/news/read/12002</link>
        <pubDate>Sun, 12 Jul 2026 04:00:00 +0900</pubDate></item>
      <item><title>Bad timestamp is isolated</title><link>/bad/12003</link>
        <pubDate>not-a-time</pubDate></item>
      <item><title>Missing link is isolated</title>
        <pubDate>Sun, 12 Jul 2026 03:00:00 +0900</pubDate></item>
      <item><title>Unsafe link is isolated</title><link>javascript:alert(1)</link>
        <pubDate>Sun, 12 Jul 2026 02:00:00 +0900</pubDate></item>
      <item><title>Relative link is isolated</title><link>/article/12004</link>
        <pubDate>Sun, 12 Jul 2026 01:00:00 +0900</pubDate></item>
    </channel></rss>"""

    articles = parse_feed(content)

    assert articles == (
        RawArticle(
            title="Residents challenge a permit",
            link="https://press.test/article/view?item=12001",
            summary="Council response & public comment",
            published=datetime.fromisoformat("2026-07-12T05:30:00+09:00"),
        ),
        RawArticle(
            title="Summary is optional here",
            link="https://press.test/news/read/12002",
            summary="",
            published=datetime.fromisoformat("2026-07-12T04:00:00+09:00"),
        ),
    )
    with pytest.raises(FrozenInstanceError):
        delattr(articles[0], "title")


def test_namespaced_atom_uses_href_iso_time_and_updated_fallback() -> None:
    content = b"""<feed xmlns="http://www.w3.org/2005/Atom">
      <entry><title>First namespaced entry</title>
        <link rel="alternate" href="https://press.test/story/88001" />
        <summary>Short abstract</summary>
        <published>2026-07-12T01:02:03Z</published></entry>
      <entry><title>Updated fallback entry</title>
        <link href="https://press.test/detail/88002" />
        <updated>2026-07-11T21:00:00+09:00</updated></entry>
    </feed>"""

    articles = parse_feed(content)

    assert tuple(article.title for article in articles) == (
        "First namespaced entry",
        "Updated fallback entry",
    )
    assert articles[0].link.endswith("/story/88001")
    assert articles[0].summary == "Short abstract"
    first_publication = articles[0].published
    second_publication = articles[1].published
    assert isinstance(first_publication, datetime)
    assert isinstance(second_publication, datetime)
    assert first_publication.utcoffset() == timedelta(0)
    assert second_publication.utcoffset() == timedelta(hours=9)


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        (b"", FeedParseReason.EMPTY),
        (b"   \n", FeedParseReason.EMPTY),
        (b"<!doctype html><html><body>blocked</body></html>", FeedParseReason.HTML),
        (b"<rss><channel><item></rss>", FeedParseReason.MALFORMED_XML),
        (b"<rss><channel></channel></rss>", FeedParseReason.ZERO_VALID_ITEMS),
        (
            b"<rss><channel><item><title>Incomplete</title></item></channel></rss>",
            FeedParseReason.ZERO_VALID_ITEMS,
        ),
    ],
)
def test_invalid_feed_payloads_have_typed_reasons(
    content: bytes,
    reason: FeedParseReason,
) -> None:
    with pytest.raises(FeedParseError) as error:
        _ = parse_feed(content)

    assert error.value.reason is reason


def test_feed_discovery_is_advertised_same_site_deduped_and_capped() -> None:
    html = """
      <link rel="alternate stylesheet" type="application/rss+xml" href="/rss/main.xml">
      <link rel="alternate" type="application/atom+xml" href="https://m.alpha.co.kr/feed.xml#top">
      <a href="/rss/main.xml#again">RSS repeat</a>
      <a href="https://desk.alpha.co.kr/custom/feed">News feed</a>
      <a href="https://alpha.co.kr/fourth/rss.xml">RSS</a>
      <a href="https://alpha.co.kr/not-advertised">ordinary page</a>
      <a href="https://alpha.co.kr.evil.test/rss.xml">RSS external</a>
      <a href="javascript:alert(1)">RSS script</a>
    """

    assert discover_feed_urls(html, "https://www.alpha.co.kr/home") == (
        "https://www.alpha.co.kr/rss/main.xml",
        "https://m.alpha.co.kr/feed.xml",
        "https://desk.alpha.co.kr/custom/feed",
    )
    assert discover_feed_urls(html, "https://www.alpha.co.kr/home", limit=1) == (
        "https://www.alpha.co.kr/rss/main.xml",
    )
    assert discover_feed_urls(html, "https://www.alpha.co.kr/home", limit=9) == (
        "https://www.alpha.co.kr/rss/main.xml",
        "https://m.alpha.co.kr/feed.xml",
        "https://desk.alpha.co.kr/custom/feed",
    )


def test_homepage_articles_accept_generic_families_and_numeric_paths() -> None:
    decoded_euc_kr_fixture = """
      <article>
        <a href="/article/view?id=41001#first"><span>주민 대책 요구 기사</span></a>
        <a href="/article/view?id=41001#second">중복 기사는 제거된다</a>
        <time datetime="2026-07-12">2026.07.12</time>
      </article>
      <a data-published="2026-07-12"
         href="https://m.alpha.co.kr/custom/story/42002">상인 단체 반발 소식</a>
      <a href="/2026/07/12/43003">숫자 경로 형식 기사</a>
    """
    run_day = date(2026, 7, 12)

    articles = parse_homepage_articles(
        decoded_euc_kr_fixture,
        "https://www.alpha.co.kr/",
        run_day,
    )

    assert tuple(article.link for article in articles) == (
        "https://www.alpha.co.kr/article/view?id=41001",
        "https://m.alpha.co.kr/custom/story/42002",
        "https://www.alpha.co.kr/2026/07/12/43003",
    )
    assert all(article.summary == "" for article in articles)
    assert all(
        article.published == CurrentDayPublication(run_day) for article in articles
    )


def test_homepage_articles_require_explicit_nonfuture_publication_evidence() -> None:
    html = """
      <a href="/article/view?id=51001">날짜 근거가 없는 기사 제목</a>
      <a href="/2026/07/11/article/51002">이전 날짜 기사 제목</a>
      <a href="/2026/07/12/article/51003">실행 날짜 기사 제목</a>
      <a href="/article/view?id=51004&amp;date=20260712">쿼리 날짜 기사 제목</a>
      <a href="/2026/07/13/article/51005">미래 날짜 기사 제목</a>
    """

    articles = parse_homepage_articles(
        html,
        "https://alpha.test/",
        date(2026, 7, 12),
    )

    assert tuple(article.link for article in articles) == (
        "https://alpha.test/2026/07/11/article/51002",
        "https://alpha.test/2026/07/12/article/51003",
        "https://alpha.test/article/view?id=51004&date=20260712",
    )
    assert articles[0].published == CurrentDayPublication(date(2026, 7, 11))


def test_homepage_articles_use_local_semantic_date_not_page_date() -> None:
    html = """
      <time datetime="2026-07-12">페이지 갱신일</time>
      <section>
        <a href="/article/61001">전역 날짜를 상속하면 안 되는 기사</a>
        <a href="/article/61002">같은 목록의 다른 기사 제목</a>
      </section>
      <article>
        <a href="/article/61003">로컬 날짜가 있는 기사 제목</a>
        <span class="published-date">2026.07.12</span>
      </article>
      <article>
        <a href="/article/61004">로컬 날짜가 오래된 기사 제목</a>
        <time datetime="2026-07-11T23:59:00+09:00"></time>
      </article>
    """

    articles = parse_homepage_articles(
        html,
        "https://alpha.test/",
        date(2026, 7, 12),
    )

    assert tuple(article.link for article in articles) == (
        "https://alpha.test/article/61003",
        "https://alpha.test/article/61004",
    )
    assert articles[1].published == datetime.fromisoformat(
        "2026-07-11T23:59:00+09:00",
    )


def test_homepage_articles_never_promote_anchor_body_to_title() -> None:
    long_body = "본문처럼 반복되는 긴 텍스트 " * 40
    html = f"""
      <article>
        <a href="/article/71001">
          <h2>군청 계획에 주민 단체 반발</h2>
          <p>{long_body}</p>
        </a>
        <time datetime="2026-07-12"></time>
      </article>
      <article>
        <a href="/article/71002">{long_body}</a>
        <time datetime="2026-07-12"></time>
      </article>
    """

    articles = parse_homepage_articles(
        html,
        "https://alpha.test/",
        date(2026, 7, 12),
    )

    assert tuple((article.link, article.title) for article in articles) == (
        ("https://alpha.test/article/71001", "군청 계획에 주민 단체 반발"),
    )


@pytest.mark.parametrize(
    "href",
    [
        "https://evil.test/article/view?id=51001",
        "/nav/article/51002",
        "/list/article/51003",
        "/category/news/51004",
        "/search/read/51005?q=x",
        "/login/story/51006",
        "/media/news/51007",
        "/assets/article/51008",
        "/static/detail/51009",
        "/article/photo-51010.jpg",
        "/null/article/51011",
        "/undefined/article/51012",
        "javascript:location='/article/51013'",
        "mailto:desk@alpha.test",
        "tel:51014",
        "data:text/plain,51015",
        "#article-51016",
        "/article/view?name=no-number",
        "/ordinary/path?id=51017",
        "/news/articleList.html?id=51018",
        "/mediaView.html?id=51019",
    ],
)
def test_homepage_articles_reject_unsafe_or_non_article_links(href: str) -> None:
    html = f'<a href="{href}">충분히 긴 기사 제목</a>'

    assert parse_homepage_articles(html, "https://alpha.test/", date(2026, 7, 12)) == ()


def test_homepage_articles_require_visible_title_of_six_characters() -> None:
    html = """
      <a href="/article/61001"></a>
      <a href="/article/61002">짧은제목</a>
      <a hidden href="/article/61003">숨겨진 기사 제목</a>
      <a aria-hidden="true" href="/article/61004">숨겨진 기사 제목</a>
      <nav hidden><a href="/article/61005">부모가 숨긴 기사 제목</a></nav>
    """

    assert parse_homepage_articles(html, "https://alpha.test/", date(2026, 7, 12)) == ()


def test_handoff_reporting_accepts_safe_meta_or_literal_js_only() -> None:
    meta_html = '<meta http-equiv="refresh" content="0; URL=/mobile/home#top">'
    js_html = """
      <script>window.location.href = 'https://evil.test/takeover';</script>
      <script>location.replace('/reader/start'); throw new Error('not run');</script>
    """

    assert reported_handoff_url(meta_html, "https://alpha.test/") == (
        "https://alpha.test/mobile/home"
    )
    assert reported_handoff_url(js_html, "https://alpha.test/") == (
        "https://alpha.test/reader/start"
    )
    assert (
        reported_handoff_url(
            "<script>location.href = buildUrl();</script>",
            "https://alpha.test/",
        )
        is None
    )
