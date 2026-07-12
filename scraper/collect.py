"""Direct executable for the regional-news collection batch."""

import runpy
import sys
from pathlib import Path

if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parents[1]
    root_text = str(repo_root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    _ = runpy.run_module("scraper.collect_runtime", run_name="__main__")
