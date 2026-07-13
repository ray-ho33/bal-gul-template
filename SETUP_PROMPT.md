# ChatGPT 셋업 프롬프트

아래 프롬프트의 저장소 자리 한 곳을 내 GitHub 저장소 주소로 바꾼 뒤, 쓰기 가능한 GitHub 플러그인이 설치된 ChatGPT Work 대화에 전체를 붙여넣으세요.

```text
내 bal-gul 저장소는 <OWNER/REPO> 이다.

이 저장소에 승인된 GitHub 플러그인만 사용해 다음 순서로 설치를 검증하고 예약 작업을 만들어라. 저장소를 clone하거나 로컬 shell, 외부 LLM API, API key를 사용하지 마라.

1. 대상 저장소와 기본 브랜치 main에 접근할 수 있는지 확인하고, main의 automation/codex-report-task.md를 읽어라. 그 파일을 매 실행의 단일 작업 지시서로 사용하되 수정하지 마라.
2. GitHub 플러그인에 저장소 파일·경로별 커밋 이력·Actions 실행을 읽는 도구와, reports 경로의 파일을 생성 또는 갱신해 main에 일반 커밋을 올리는 쓰기 도구가 실제로 있는지 확인하라. 검색용 읽기 전용 GitHub 앱만 있거나 필요한 권한을 증명할 수 없으면 예약 작업을 만들지 말고 정확히 무엇이 부족한지 알려라.
3. .github/workflows/collect.yml이 존재하는지 확인하라. 현재 Asia/Seoul 날짜의 data/candidates 파일, 그 경로의 최신 source commit SHA와 blob SHA, JSON의 workflow_run_url을 확인하고, 해당 Actions 실행의 conclusion이 success인지 검증하라.
4. automation/codex-report-task.md의 준비 상태 규칙에 따라 현재 KST 날짜를 검증 전용 날짜로 삼아 readiness만 수동 검사하라. 기존 리포트를 생성·수정·삭제하지 마라. 하나라도 통과하지 못하면 NOT_READY 이유와 사용자가 GitHub 웹에서 해야 할 조치를 알려주고 예약 작업을 만들지 마라.
5. 모두 통과하면 매일 07:30 Asia/Seoul에 독립적으로 실행되는 예약 작업을 만들어라. 이 시각은 06:00 GitHub Actions 예약 실행의 지연을 흡수하기 위한 90분 간격이다. 각 실행은 이 저장소를 대상으로 GitHub 플러그인을 사용해 automation/codex-report-task.md 전체를 그대로 수행해야 한다. 날짜를 고정하지 말고 실행 시점의 현재 KST 날짜를 사용하라.
6. 작업 생성 후 작업 이름, 대상 저장소, 일정과 시간대, 사용하도록 연결된 GitHub 플러그인, 다음 실행 시각을 보여라. 사용자가 Scheduled 화면에서 확인할 체크리스트와 첫 수동 실행 방법도 알려라.

검증하거나 생성하지 못한 항목을 성공했다고 추측하지 마라. GitHub 쓰기 권한이 없으면 다른 경로로 우회하지 마라.
```
