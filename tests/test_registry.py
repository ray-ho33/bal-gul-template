from pathlib import Path
from typing import Literal

import pytest
from pydantic import ValidationError
from scraper.registry import (
    DuplicateSourceError,
    RegistryCountError,
    RegistryReadError,
    RegistrySchemaError,
    load_registry,
    parse_registry_json,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_MODULE = REPO_ROOT / "scraper" / "registry.py"
REGISTRY_PATH = REPO_ROOT / "korean_regional_newspapers.json"
SEVEN_EMPTY_GROUPS = b"""{
  "source": "registry fixture",
  "retrieved": "2026-07-11",
  "regions": {"1": [], "2": [], "3": [], "4": [], "5": [], "6": [], "7": []}
}"""
ONE_EMPTY_REGION = b"""{
  "source": "registry fixture",
  "retrieved": "2026-07-11",
  "regions": {"only": []}
}"""


def _registry_text() -> str:
    return REGISTRY_PATH.read_text(encoding="utf-8")


def test_registry_production_surface_exists() -> None:
    # Given: the agreed M1 registry module path
    # When: the production surface is inspected
    # Then: the module exists
    assert REGISTRY_MODULE.is_file()


def test_real_registry_has_exact_source_and_region_counts() -> None:
    # Given: the existing registry file
    # When: its strict JSON boundary is loaded
    sources = load_registry(REGISTRY_PATH)

    # Then: all 88 sources across all 7 parent groups are returned
    assert len(sources) == 88
    assert len({source.region for source in sources}) == 7


def test_parent_region_is_injected_into_each_source() -> None:
    # Given: records nested beneath parent region keys
    # When: the registry is flattened
    sources = load_registry(REGISTRY_PATH)

    # Then: a record carries its parent key as its typed region
    gangwon_ilbo = next(source for source in sources if source.name == "강원일보")
    assert gangwon_ilbo.region == "강원권"


def test_output_tuple_and_source_are_immutable() -> None:
    # Given: a parsed registry
    sources = load_registry(REGISTRY_PATH)

    # When/Then: the collection has no mutable sequence surface
    assert isinstance(sources, tuple)
    assert not hasattr(sources, "append")

    # When/Then: Pydantic rejects field mutation on a source
    with pytest.raises(ValidationError, match="Instance is frozen"):
        sources[0].name = "변경"


@pytest.mark.parametrize(
    ("original", "duplicate", "field", "value"),
    [
        ("강원도민일보", "강원일보", "name", "강원일보"),
        (
            "http://www.kado.net/",
            "http://www.kwnews.co.kr/",
            "homepage",
            "http://www.kwnews.co.kr/",
        ),
    ],
)
def test_duplicate_sources_are_rejected(
    original: str,
    duplicate: str,
    field: Literal["name", "homepage"],
    value: str,
) -> None:
    # Given: an 88-entry registry with one duplicated identity field
    raw = _registry_text().replace(
        f'"{original}"',
        f'"{duplicate}"',
        1,
    )

    # When: the duplicate crosses the registry boundary
    with pytest.raises(DuplicateSourceError) as error:
        _ = parse_registry_json(raw)

    # Then: a structured duplicate error identifies it
    assert error.value.field == field
    assert error.value.value == value


def test_non_http_homepage_is_rejected() -> None:
    # Given: a homepage using a non-HTTP transport
    raw = _registry_text().replace(
        "http://www.kwnews.co.kr/",
        "ftp://www.kwnews.co.kr/",
        1,
    )

    # When/Then: the schema boundary rejects it with a domain error
    with pytest.raises(RegistrySchemaError):
        _ = parse_registry_json(raw)


@pytest.mark.parametrize(
    ("original", "blank"),
    [
        ("강원일보", "   "),
        ("강원권", "   "),
        ("http://www.kwnews.co.kr/", "   "),
        ("https://namu.wiki/w/신문/목록#s-2.1.1", "   "),
    ],
)
def test_blank_fields_are_rejected(original: str, blank: str) -> None:
    # Given: a required string field containing only whitespace
    raw = _registry_text().replace(f'"{original}"', f'"{blank}"', 1)

    # When/Then: the schema boundary rejects it with a domain error
    with pytest.raises(RegistrySchemaError):
        _ = parse_registry_json(raw)


@pytest.mark.parametrize(
    "raw",
    [
        b"{}",
        b"[]",
        (b'{"source":"fixture","retrieved":"2026-07-11","regions":[]}'),
        (
            b'{"source":"fixture","retrieved":"2026-07-11",'
            b'"regions":{},"unexpected":true}'
        ),
    ],
)
def test_malformed_envelopes_are_rejected(raw: bytes) -> None:
    # Given: JSON that violates the exact nested envelope
    # When/Then: the boundary translates it to a typed domain error
    with pytest.raises(RegistrySchemaError):
        _ = parse_registry_json(raw)


@pytest.mark.parametrize(
    ("raw", "scope", "actual"),
    [
        (ONE_EMPTY_REGION, "regions", 1),
        (SEVEN_EMPTY_GROUPS, "sources", 0),
    ],
)
def test_wrong_registry_counts_are_rejected(
    raw: bytes,
    scope: Literal["regions", "sources"],
    actual: int,
) -> None:
    # Given: a valid envelope with the wrong cardinality
    # When: it crosses the registry boundary
    with pytest.raises(RegistryCountError) as error:
        _ = parse_registry_json(raw)

    # Then: a structured count error identifies the mismatch
    assert error.value.scope == scope
    assert error.value.actual == actual


def test_registry_file_is_not_mutated_during_loading() -> None:
    # Given: the original registry bytes
    before = REGISTRY_PATH.read_bytes()

    # When: the real file is loaded
    _ = load_registry(REGISTRY_PATH)

    # Then: the source blob remains byte-identical
    assert REGISTRY_PATH.read_bytes() == before


def test_file_read_failure_is_a_typed_domain_error(tmp_path: Path) -> None:
    # Given: an explicit path that does not exist
    missing = tmp_path / "missing.json"

    # When/Then: the adapter exposes a typed read error
    with pytest.raises(RegistryReadError) as error:
        _ = load_registry(missing)

    assert error.value.path == missing
