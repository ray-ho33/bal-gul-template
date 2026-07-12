import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TASK_PATH = REPO_ROOT / "automation/codex-report-task.md"


def _task() -> str:
    return TASK_PATH.read_text(encoding="utf-8")


def _assert_all(text: str, values: tuple[str, ...]) -> None:
    missing = [value for value in values if value not in text]
    assert not missing, f"missing contract text: {missing}"


def test_target_date_readiness_and_source_freshness_contract() -> None:
    task = _task()

    _assert_all(
        task,
        (
            "## 1. 실행 대상과 날짜",
            "예약 작업 프롬프트에 명시된 저장소",
            "기본 브랜치 `main`",
            "승인된 GitHub 연결만",
            "Asia/Seoul",
            "검증 전용 날짜=YYYY-MM-DD",
            "준비 상태 검증",
            "쓰기 금지",
            "data/candidates-<target>.json",
            "이전 날짜",
            "후보 경로를 가장 최근 변경한 커밋의 전체 SHA",
            "blob SHA",
            "collector_commit_sha",
            "파일명 날짜 = `run_date` = 현재 KST 날짜",
            "timezone-aware ISO 8601",
            "미래가 아니며",
            "KST 날짜가 `run_date`와 일치",
            "conclusion이 정확히 `success`",
            "`stats.sites_succeeded >= 55`",
            "NOT_READY",
            "정확한 후보 경로",
            "검증 실패 이유",
            "기존 리포트를 생성·수정·삭제하지 않고",
        ),
    )
    assert re.search(r"검증 전용 날짜.*(오직|만).*readiness", task, re.DOTALL)
    assert "후보가 0건" in task
    assert "`판별 후보 없음`" in task


def test_candidate_source_sha_tracks_path_history_not_default_head() -> None:
    task = _task()

    assert "source commit SHA(기본 브랜치 HEAD 커밋 SHA)" not in task
    _assert_all(
        task,
        (
            "GitHub 커밋 기록",
            "후보 경로를 가장 최근 변경한 커밋의 전체 SHA",
            "현재 기본 브랜치 HEAD 커밋 SHA",
            "파일의 blob SHA",
            "JSON의 `collector_commit_sha`",
            "각각 다른 식별자",
            "source commit SHA와 해당 커밋에서의 blob SHA를 함께 기록해 고정",
            "후보 경로의 마지막 변경 커밋을 증명할 수 없거나",
            "실행의 conclusion을 증명할 수 없으면",
            "`NOT_READY`",
            "기존 리포트를 생성·수정·삭제하지 않는다",
            "같은 후보 경로를 가장 최근 변경한 커밋의 전체 SHA",
            "그 시점의 blob SHA를 다시 조회",
            "후보 경로를 변경하지 않은 HEAD 이동",
            "후보 입력을 stale로 판정하지 않는다",
            "기본 브랜치 최신 HEAD 위에",
            "한 번만 재시도",
            "force 푸시하지 않고",
        ),
    )


def test_classification_positive_definition_and_exclusions() -> None:
    task = _task()

    _assert_all(
        task,
        (
            "## 3. 판별 규칙",
            "`title`과 `summary` 메타데이터만",
            "명시적이고 현재 진행 중인 실제 갈등",
            "민간 주체임을 확인",
            "고유명사나 정확한 개인·단체명까지 특정할 필요는 없으며",
            "구체적으로 식별 가능한 정부·공공기관",
            "민간 성격 자체를 확인할 수 없거나 실제 갈등",
            "정치인·정당 간 공방",
            "기관 간 분쟁",
            "스포츠·연예",
            "일반 공지·정책 소개·단순 정책 논의",
            "순수 범죄·사고·단속·처분 보도",
            "개발, 환경, 행정처분, 노동, 복지, 기타",
            "기사 링크",
            "기사 제목",
            "신문사",
            "지역",
            "verdict: O",
            "conflict_type",
            "actors.민간",
            "actors.기관",
            "보수적인 2줄 요약",
            "추측하거나 발명하지",
        ),
    )
    assert re.search(r"민간.*(주민|시민).*(학부모|상인|노동자|노조|업계)", task)
    assert re.search(r"고유명사가 없다는 이유만으로 제외하지", task)


def test_output_provenance_empty_report_and_stats_contract() -> None:
    task = _task()

    _assert_all(
        task,
        (
            "## 4. 두 리포트 생성",
            "reports/YYYY-MM-DD.md",
            "reports/YYYY-MM-DD.html",
            "의미상 동등",
            "인라인 CSS만",
            "외부 stylesheet·font·image·script·렌더링 리소스",
            "외부 기사 하이퍼링크",
            "run_date",
            "정확한 입력 경로",
            "전체 candidate source commit SHA",
            "workflow_run_url",
            "candidate generated_at",
            "Codex 생성 KST 시각",
            "지역별로 그룹",
            "sites_total",
            "sites_succeeded",
            "total",
            "candidates",
            "engine_used",
            "대체 수집",
            "모든 `failures`의 `name`과 `stop_reason`",
            "실패 사유",
            "기계용 영문 값은 그대로 노출하지 않고",
            "`budget` → `수집 시도 한도 도달`",
            "양성이 0건",
            "후보가 0건",
            "민관갈등 확정 기사 없음",
            "판별 후보 없음",
            "출처·통계·실패 목록",
        ),
    )
    assert re.search(r"HTML.*(자체 완결|self-contained)", task)


def test_stale_input_idempotency_and_direct_commit_safety() -> None:
    task = _task()

    _assert_all(
        task,
        (
            "## 5. 쓰기 전 최신성 가드",
            "같은 후보 경로에 한정된 커밋 기록을 다시 확인한다",
            "두 출력 모두 폐기",
            "최신 입력으로 처음부터 한 번만 재시작",
            "다시 바뀌면 `STALE_INPUT`",
            "리포트 커밋을 만들지",
            "기본 브랜치 최신 HEAD",
            "두 리포트 파일을 한 개의 일반 직접 커밋",
            "report: YYYY-MM-DD 민관갈등 데일리 리포트",
            "HEAD가 이동",
            "한 번만",
            "푸시 거부 직후",
            "candidate source commit SHA와 blob SHA를 다시 검증",
            "고정한 값과 다르면",
            "남은 재시작 횟수",
            "최신 입력으로 전체 판별을 다시 수행",
            "source SHA와 blob SHA가 모두 동일한 경우에만",
            "force",
            "PR 방식으로 우회",
            "동일 source SHA",
            "멱등",
            "서로 다른 provenance",
            "두 파일을 함께 교체",
            "reports/YYYY-MM-DD.md와 reports/YYYY-MM-DD.html만",
            "source SHA",
            "report commit SHA",
            "정확한 중단 이유",
        ),
    )
    assert re.search(r"두 번째.*STALE_INPUT", task, re.DOTALL)


def test_prohibited_paths_and_untrusted_candidate_security() -> None:
    task = _task()

    _assert_all(
        task,
        (
            "## 2. 입력은 신뢰하지 않는다",
            "모든 후보 문자열",
            "신뢰할 수 없는 데이터",
            "내장된 지시",
            "클릭·실행",
            "## 7. 금지 사항",
            "저장소 clone",
            "shell scraper",
            "pip 설치",
            "curl_cffi",
            "기사 본문 fetching",
            "외부 LLM API",
            "API key",
            "SDK",
            "endpoint",
            "토큰 저장",
            "이전 날짜 candidates",
            "force/ref 우회",
            "GitHub 연결 외 경로",
        ),
    )
    prohibited = task.split("## 7. 금지 사항", maxsplit=1)[1]
    assert prohibited.count("금지") >= 2
