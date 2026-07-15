import re
from pathlib import Path
from typing import Final

from scraper.registry import load_registry

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "korean_regional_newspapers.json"
README_PATH = REPO_ROOT / "README.md"
MARKDOWN_SAMPLE_PATH = REPO_ROOT / "examples/sample-report.md"
HTML_SAMPLE_PATH = REPO_ROOT / "examples/sample-report.html"
HTML_STAT_VALUE_PATTERN: Final = (
    r'<div class="stat"><div class="num(?: accent)?">(?P<value>\d+)</div>'
)
HTML_STAT_LABEL_PATTERN: Final = r'<div class="label">(?P<label>[^<]+)</div></div>'
HTML_STAT_PATTERN: Final[re.Pattern[str]] = re.compile(
    f"{HTML_STAT_VALUE_PATTERN}{HTML_STAT_LABEL_PATTERN}",
)


def test_documented_source_counts_match_registry_contract() -> None:
    # Given: the registry and source counts shown in the workflow diagram and samples
    registry = load_registry(REGISTRY_PATH)
    readme = README_PATH.read_text(encoding="utf-8")
    markdown = MARKDOWN_SAMPLE_PATH.read_text(encoding="utf-8")
    html = HTML_SAMPLE_PATH.read_text(encoding="utf-8")

    # When: each user-facing count is parsed from its structured location
    registry_total = len(registry)
    diagram_match = re.search(r'A\["전국 (\d+)개 지역신문 목록"\]', readme)
    assert diagram_match is not None
    diagram_total = int(diagram_match.group(1))
    markdown_total = _markdown_stat(markdown, "대상 신문사")
    markdown_succeeded = _markdown_stat(markdown, "수집 성공")
    markdown_failures = _markdown_failure_count(markdown)
    html_stats = {
        match.group("label"): int(match.group("value"))
        for match in HTML_STAT_PATTERN.finditer(html)
    }
    html_failures = (
        html.split('<section id="failures">', maxsplit=1)[1]
        .split("</section>", maxsplit=1)[0]
        .count("<tr><td>")
    )

    # Then: every document covers the same registry and accounts for every source
    assert diagram_total == registry_total
    assert markdown_total == registry_total
    assert markdown_succeeded + markdown_failures == registry_total
    assert html_stats["대상 신문사"] == registry_total
    assert html_stats["수집 성공"] + html_failures == registry_total


def _markdown_stat(markdown: str, label: str) -> int:
    match = re.search(rf"^\| {re.escape(label)} \| (\d+) \|$", markdown, re.MULTILINE)
    assert match is not None
    return int(match.group(1))


def _markdown_failure_count(markdown: str) -> int:
    section = markdown.split("## 수집 실패 목록", maxsplit=1)[1].split(
        "## Provenance", maxsplit=1
    )[0]
    return sum(
        line.startswith("| ")
        for line in section.splitlines()
        if line not in {"| 신문사 | 실패 사유 |", "|---|---|"}
    )
