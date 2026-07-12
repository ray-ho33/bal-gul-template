"""Contract tests for the vendored insane-search engine snapshot."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path
from typing import Final

_ENGINE_ROOT: Final = Path(__file__).resolve().parents[1] / "vendor" / "engine"
_SOURCE_PATH: Final = "skills/insane-search/engine"
_SNAPSHOT_SHA256: Final = {
    "LICENSE": "e343d30bc6631a1c8377b7aac26e7b1c5b38366913a98ef71fe6861fe812dcd4",
    "__init__.py": "fbdf2a0832bd3be821ea2dfb18f66d938ecd56a2767df66ff530355068cc1811",
    "__main__.py": "0390beb3858307942b5e9647ed995ef9379fc21c87f3d5bac3101224c62eff02",
    "bias_check.py": "606899ed7798b8b8b27d1667fdd46f2b79a5089a0b9b166354ec58966a082dd4",
    "content_safety.py": (
        "15250010928dbf8877c90c744c825ea71ef7ae57f9a9f2fb96c0eb0cc239c872"
    ),
    "executor.py": "4434133e2c6e727ff549f24045befa16bbef8895f9e3d10d21663b5fbe429de8",
    "fetch_chain.py": (
        "3d8b4c391116b1d6602d4b3fb3bc94c98b6d3416e9308d66562913117f81c90c"
    ),
    "learning.py": "4360529675d2a2eb41855ab76b7ed2a37995cf4409161c7a0ac38b2a6413bed6",
    "phase0.py": "1d1e7626748a127ff2c2082d7b64ee0254c8eb7af4c3fd1804db1f0bd71ee086",
    "safety.py": "3b78f8130db7041293aab85e53446b5f579cee08e7e7468a50880e17ff8be96e",
    "templates/.gitignore": (
        "88b6b09796bc021a6f46b5964be1cbe30ef7a25d613ee43f868e720ee4d15587"
    ),
    "templates/package-lock.json": (
        "688b41089c17da849e2806aa671c64e8145fedef432a77f869ede8039ccf2939"
    ),
    "templates/package.json": (
        "cdfe0887ea423e541153127573ab2cf2ff0d333266d33206670161d007a61613"
    ),
    "templates/playwright_mobile_chrome.js": (
        "cea1b6db5bcf4ccfd61c8487848340b6f37547de9816267f95965e87961f322e"
    ),
    "templates/playwright_real_chrome.js": (
        "568c6da4b1123364a751cf87ed947ba37ffce8a35afa29cabcb923d0a5697717"
    ),
    "transport.py": "a4e8b24628cf0f8ffc5669f45b18174e01195d10ddc8a27b99012ac13997b6ad",
    "url_transforms.py": (
        "091433e23b9f66bd6d6c0379c013589c6881d7e840c98aa6af0e018ef361de09"
    ),
    "validators.py": "ec330c5c8539be430c47a335423caf4abe87f1b8907cda659db25c624d492015",
    "waf_detector.py": (
        "5de70edda523f3680040ccbc8a1bc301c0b424d0ee98985adcaab3f5f0da790a"
    ),
    "waf_profiles.yaml": (
        "ee5da75975e23e627eed6ca54f83bd7b0a5b839cb50eeb4f059ff0251f410376"
    ),
}
_IMPORT_PROBE: Final = """\
from inspect import signature
from vendor.engine import fetch
print(*signature(fetch).parameters, sep="\\n")
"""


def test_vendor_surface_when_snapshot_is_installed() -> None:
    """Expose version, license, and package import files together."""
    # Given: the three required filesystem surfaces.
    surface_paths = (
        _ENGINE_ROOT / "VERSION",
        _ENGINE_ROOT / "LICENSE",
        _ENGINE_ROOT / "__init__.py",
    )

    # When: their installed state is observed without importing the package.
    installed = tuple(path.is_file() for path in surface_paths)

    # Then: every surface is available to consumers.
    assert installed == (True, True, True), surface_paths


def test_metadata_when_snapshot_is_installed() -> None:
    """Record the exact release identity, provenance, and MIT terms."""
    # Given: the installed version and license metadata.
    version_path = _ENGINE_ROOT / "VERSION"
    license_path = _ENGINE_ROOT / "LICENSE"

    # When: both metadata documents are read.
    version_metadata = version_path.read_text(encoding="utf-8")
    license_text = license_path.read_text(encoding="utf-8")

    # Then: release identity and upstream provenance are explicit.
    assert "version=0.9.1" in version_metadata
    assert "identity=insane-search" in version_metadata
    assert f"source_path={_SOURCE_PATH}" in version_metadata
    assert "repository=https://github.com/fivetaku/insane-search" in version_metadata
    assert "provenance=local Claude plugin cache snapshot" in version_metadata
    assert license_text.startswith("MIT License\n")
    assert "Copyright (c) 2026 fivetaku" in license_text
    assert "Permission is hereby granted, free of charge" in license_text


def test_fetch_signature_when_package_is_imported() -> None:
    """Import the public fetch function with all required feature switches."""
    # Given: a cache-free interpreter starts from the repository root.
    command = [sys.executable, "-B", "-c", _IMPORT_PROBE]

    # When: the public package surface is imported.
    completed = subprocess.run(  # noqa: S603
        command,
        cwd=_ENGINE_ROOT.parents[1],
        capture_output=True,
        check=False,
        text=True,
    )
    parameters = frozenset(completed.stdout.splitlines())

    # Then: the collector can control every required engine phase.
    assert completed.returncode == 0, completed.stderr
    assert {
        "enable_playwright",
        "enable_phase0",
        "enable_learning",
    } <= parameters


def test_snapshot_bytes_when_release_is_vendored() -> None:
    """Preserve every allowed upstream byte and no excluded directory."""
    # Given: the expected release inventory and forbidden directory names.
    expected_files = frozenset((*_SNAPSHOT_SHA256, "VERSION"))
    forbidden_names = frozenset({"tests", "node_modules"})

    # When: the complete vendored tree and file hashes are observed.
    snapshot_paths = tuple(
        path for path in _ENGINE_ROOT.rglob("*") if "__pycache__" not in path.parts
    )
    actual_files = frozenset(
        path.relative_to(_ENGINE_ROOT).as_posix()
        for path in snapshot_paths
        if path.is_file()
    )
    actual_hashes = {
        relative_path: hashlib.sha256(
            (_ENGINE_ROOT / relative_path).read_bytes()
        ).hexdigest()
        for relative_path in _SNAPSHOT_SHA256
    }

    # Then: inventory, bytes, and exclusions match the 0.9.1 snapshot exactly.
    assert actual_files == expected_files
    assert actual_hashes == _SNAPSHOT_SHA256
    assert not any(forbidden_names.intersection(path.parts) for path in snapshot_paths)
