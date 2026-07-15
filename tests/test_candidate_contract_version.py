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


def test_reader_rejects_legacy_candidate_contract() -> None:
    legacy_path = Path("data/candidates-2026-07-15.json")

    with pytest.raises(ValidationError, match="contract_version"):
        _ = read_candidate_file(legacy_path)
