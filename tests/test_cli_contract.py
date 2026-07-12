import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_cli_help_contract() -> None:
    result = subprocess.run(
        [sys.executable, "scraper/collect.py", "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "--date" in result.stdout
