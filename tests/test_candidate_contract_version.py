import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from scraper.schema import (
    CANDIDATE_CONTRACT_VERSION,
    CandidateFile,
    read_candidate_file,
)


def test_schema_production_surface_exists() -> None:
    assert Path("scraper/schema.py").is_file()


def test_candidate_contract_version_is_required_and_exact() -> None:
    schema = CandidateFile.model_json_schema()

    assert "contract_version" in schema["required"]
    assert (
        schema["properties"]["contract_version"]["const"] == CANDIDATE_CONTRACT_VERSION
    )
    with pytest.raises(ValidationError, match="contract_version"):
        _ = CandidateFile.model_validate({})
    with pytest.raises(ValidationError, match=CANDIDATE_CONTRACT_VERSION):
        _ = CandidateFile.model_validate({"contract_version": "legacy-conflict-v1"})


def test_reader_rejects_legacy_candidate_contract(tmp_path: Path) -> None:
    legacy_path = tmp_path / "candidates-2026-07-12.json"
    legacy_payload = {
        "run_date": "2026-07-12",
        "generated_at": "2026-07-12T06:00:00+09:00",
        "workflow_run_url": None,
        "collector_commit_sha": "a" * 40,
        "candidates": [],
        "failures": [
            {"name": f"실패 신문 {index}", "stop_reason": "test"} for index in range(88)
        ],
        "stats": {
            "sites_total": 88,
            "sites_succeeded": 0,
            "total": 0,
            "candidates": 0,
            "engine_used": 0,
        },
    }
    _ = legacy_path.write_text(
        json.dumps(legacy_payload, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="contract_version"):
        _ = read_candidate_file(legacy_path)
