from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github/workflows/collect.yml"


def _workflow() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def test_schedule_and_dispatch_triggers_with_minimal_policy() -> None:
    workflow = _workflow()

    triggers = '\non:\n  schedule:\n    - cron: "0 21 * * *"\n  workflow_dispatch:\n'
    assert triggers in workflow
    assert workflow.count("schedule:") == 1
    assert workflow.count('cron: "0 21 * * *"') == 1
    assert "\npermissions:\n  contents: write\n" in workflow
    assert workflow.count("permissions:") == 1
    assert "\nconcurrency:\n" in workflow
    assert "cancel-in-progress: false" in workflow
    concurrency = workflow.split("\nconcurrency:\n", 1)[1].split("\njobs:\n", 1)[0]
    assert "github.sha" not in concurrency
    assert "github.run_id" not in concurrency
    assert "github.run_number" not in concurrency


def test_pinned_checkout_runtime_and_default_branch_guard() -> None:
    workflow = _workflow()

    guard = workflow.index("Require default branch dispatch")
    checkout = workflow.index("uses: actions/checkout@v7")
    assert guard < checkout
    assert "REF_NAME: ${{ github.ref_name }}" in workflow
    assert "REF_TYPE: ${{ github.ref_type }}" in workflow
    assert "DEFAULT_BRANCH: ${{ github.event.repository.default_branch }}" in workflow
    assert (
        '[[ "$REF_TYPE" == "branch" && "$REF_NAME" == "$DEFAULT_BRANCH" ]]' in workflow
    )
    assert "ref: ${{ github.sha }}" in workflow
    assert "fetch-depth: 0" in workflow
    assert 'test "$(git rev-parse HEAD)" = "$EXPECTED_SHA"' in workflow
    assert "uses: actions/setup-python@v6" in workflow
    assert 'python-version: "3.11"' in workflow
    assert "python -m pip install --requirement vendor/requirements.txt" in workflow


def test_kst_collection_cleanup_and_handoff_validation() -> None:
    workflow = _workflow()

    assert 'RUN_DATE="$(TZ=Asia/Seoul date +%F)"' in workflow
    cleanup = 'rm -f -- "data/candidates-$RUN_DATE.json"'
    assert cleanup in workflow
    assert "rm -rf" not in workflow
    assert 'python scraper/collect.py --date "$RUN_DATE" || COLLECT_EXIT=$?' in workflow
    assert 'echo "COLLECT_EXIT=$COLLECT_EXIT" >> "$GITHUB_ENV"' in workflow
    assert "from scraper.schema import read_candidate_file" in workflow
    assert "document.run_date.isoformat() != run_date" in workflow
    assert "document.workflow_run_url != expected_run_url" in workflow
    assert "document.collector_commit_sha != expected_sha" in workflow
    assert "document.stats.sites_total != 69" in workflow
    assert (
        'output.write(f"sites_succeeded={document.stats.sites_succeeded}\\n")'
        in workflow
    )


def test_commit_push_retry_and_post_push_threshold_gate() -> None:
    workflow = _workflow()

    assert 'git config user.name "github-actions[bot]"' in workflow
    assert (
        'git config user.email "41898282+github-actions[bot]@users.noreply.github.com"'
        in workflow
    )
    assert 'git add -- "$CANDIDATE_PATH"' in workflow
    assert (
        'git commit -m "data: $RUN_DATE 기사 후보 수집" -- "$CANDIDATE_PATH"'
        in workflow
    )
    assert 'git fetch origin "$DEFAULT_BRANCH"' in workflow
    assert 'git rebase "origin/$DEFAULT_BRANCH"' in workflow
    assert workflow.count('git push origin "HEAD:$DEFAULT_BRANCH"') == 2
    assert "non-fast-forward|fetch first" in workflow
    assert "--force" not in workflow
    assert "--force-with-lease" not in workflow
    first_push = workflow.index('git push origin "HEAD:$DEFAULT_BRANCH"')
    final_gate = workflow.index(
        'if [[ "$COLLECT_EXIT" -ne 0 || "$SITES_SUCCEEDED" -lt 55 ]]'
    )
    assert first_push < final_gate
    assert '"$SITES_SUCCEEDED" -lt 55' in workflow
    assert '"$SITES_SUCCEEDED" -eq 55' not in workflow
    assert (
        "document.stats.candidates"
        not in workflow.split("Enforce collection readiness", 1)[1]
    )


def test_workflow_has_no_external_llm_integration_strings() -> None:
    workflow = _workflow().lower()
    forbidden = (
        "openai" + "_api_key",
        "anthropic" + "_api_key",
        "api." + "openai.com",
        "api." + "anthropic.com",
    )

    assert not any(value in workflow for value in forbidden)
