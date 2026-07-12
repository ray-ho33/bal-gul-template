# bal-gul 설치 가이드

이 가이드는 터미널 없이 GitHub 웹과 ChatGPT만으로 설치하는 절차입니다. 보통 5~10분이 걸리지만, GitHub의 첫 수집은 신문사 응답 속도에 따라 더 오래 걸릴 수 있습니다.

## 준비물

- GitHub 계정
- ChatGPT Plus 이상 계정
- ChatGPT Work의 `Scheduled`와 `Plugins` 메뉴
- 저장소 읽기와 쓰기 작업을 제공하는 GitHub 플러그인

계정이나 워크스페이스에서 Work, Scheduled, Plugins 중 하나가 보이지 않으면 해당 기능이 활성화되어 있는지 먼저 확인하세요. 관리형 워크스페이스에서는 관리자가 플러그인 또는 외부 쓰기 작업을 제한할 수 있습니다.

## 1. 내 저장소 만들기

1. bal-gul 템플릿 저장소의 첫 화면으로 이동합니다.
2. 파일 목록 위의 **Use this template**을 누릅니다.
3. **Create a new repository**를 선택합니다.
4. Owner를 고르고 원하는 저장소 이름을 입력합니다.
5. 기사 후보와 리포트를 공개하고 싶지 않다면 **Private**을 선택합니다.
6. **Create repository from template**을 누릅니다.

> [스크린샷 자리 1: Use this template 버튼과 Create a new repository 메뉴]

새 저장소의 기본 브랜치가 `main`인지 확인하세요. 이 배포판의 예약 작업 지시서는 `main`을 기준으로 합니다.

## 2. 기사 수집을 한 번 실행하기

1. 새 저장소 위쪽의 **Actions** 탭을 엽니다.
2. GitHub가 workflow 활성화를 묻는다면 **I understand my workflows, go ahead and enable them**을 누릅니다.
3. 왼쪽에서 **Collect article candidates**를 선택합니다.
4. 오른쪽의 **Run workflow**를 누릅니다.
5. Branch가 `main`인지 확인하고 초록색 **Run workflow** 버튼을 누릅니다.

> [스크린샷 자리 2: Actions의 Collect article candidates와 Run workflow 버튼]

실행 항목을 눌러 완료될 때까지 기다립니다.

- 초록색 체크: 수집 준비 상태 통과
- 빨간색 X: 실행 로그를 열어 실패 이유 확인

수집 성공 신문사가 55곳 미만이면 workflow는 빨간색으로 끝나지만, 진단용 `data/candidates-YYYY-MM-DD.json`은 저장소에 남을 수 있습니다. 이 파일이 있다는 사실만으로 설치 성공은 아닙니다. 06:20 예약 작업은 성공한 Actions 실행과 55곳 이상 수집을 모두 요구합니다.

초록색으로 끝났다면 저장소 첫 화면에서 `data` 폴더를 열고 오늘 날짜의 `candidates-YYYY-MM-DD.json`이 있는지 확인합니다.

## 3. 쓰기 가능한 GitHub 플러그인 연결하기

이 단계에서는 일반 검색용 GitHub 앱이 아니라, 저장소 파일을 읽고 커밋할 수 있는 GitHub 플러그인이 필요합니다.

1. ChatGPT 웹에서 **Work**를 선택합니다.
2. **Plugins**를 열고 GitHub 플러그인을 찾습니다.
3. **Install** 또는 **Connect**를 누르고 GitHub에 로그인합니다.
4. 방금 만든 저장소에 대한 접근을 허용합니다.
5. 설치 후 새 Work 대화를 엽니다.

> [스크린샷 자리 3: ChatGPT Work의 Plugins 화면과 GitHub 플러그인]

반드시 다음을 확인하세요.

- 플러그인이 저장소 파일과 커밋 이력을 읽을 수 있음
- Actions 실행 상태를 조회할 수 있음
- 저장소 파일을 생성·갱신하고 기본 브랜치에 커밋할 수 있음

ChatGPT **Settings → Apps**에서 연결하는 검색용 GitHub 앱만 보이고 쓰기 작업이 없다면 여기서 중단하세요. OpenAI의 일반 GitHub 앱은 코드 검색·분석용 읽기 연결일 수 있으며, 그것만으로는 리포트 커밋을 만들 수 없습니다.

## 4. 셋업 프롬프트 붙여넣기

1. [SETUP_PROMPT.md](SETUP_PROMPT.md)를 엽니다.
2. 프롬프트 안의 저장소 자리 한 곳을 내 GitHub 저장소 주소로 바꿉니다. 예: `my-name/my-bal-gul`.
3. 전체 프롬프트를 ChatGPT Work의 새 대화에 붙여넣습니다.
4. ChatGPT가 연결, Actions 성공, 오늘 후보 파일, 쓰기 도구를 검증하게 둡니다.
5. 모든 검증이 통과했을 때만 매일 06:20 KST 예약 작업을 만들도록 승인합니다.

> [스크린샷 자리 4: 프롬프트를 붙여넣은 Work 대화와 예약 작업 확인 카드]

ChatGPT가 권한이나 실행 상태를 증명하지 못하면 예약 작업을 만들었다고 간주하지 마세요. 문제를 해결한 뒤 같은 프롬프트로 다시 검증합니다.

## 5. 설치 완료 확인

ChatGPT가 만든 예약 작업에서 다음 항목을 확인합니다.

- [ ] 작업 대상 저장소가 내 저장소와 정확히 일치함
- [ ] `automation/codex-report-task.md`를 매 실행의 지시서로 사용함
- [ ] 매일 06:20, 시간대 `Asia/Seoul`로 설정됨
- [ ] GitHub 플러그인이 예약 작업에서 사용 가능함
- [ ] 다음 실행 시각이 표시됨

첫 설치 때는 예약 작업을 한 번 수동 실행해 끝까지 확인하는 것을 권장합니다. 같은 날 2단계에서 Actions가 이미 성공한 상태여야 합니다.

- [ ] 실행 결과가 `NOT_READY`가 아닌 성공으로 끝남
- [ ] `reports/YYYY-MM-DD.md`와 `reports/YYYY-MM-DD.html`이 한 커밋에 함께 생김
- [ ] 커밋에는 위 두 파일 외의 변경이 없음
- [ ] 리포트의 날짜, 입력 경로, source SHA, blob SHA, workflow URL이 오늘 후보와 일치함
- [ ] 같은 입력으로 다시 실행했을 때 새 커밋이 생기지 않음

이 실셋업 확인은 사용자 계정의 ChatGPT와 GitHub 권한이 필요하므로 템플릿 저장소에서 대신 자동화할 수 없습니다.

## 운영 한계와 비용

### 예약 작업은 최초 1회 수동 등록

GitHub 템플릿은 ChatGPT 계정 안에 예약 작업을 자동으로 설치할 수 없습니다. 사용자가 셋업 프롬프트를 붙여넣고 작업 생성을 확인해야 합니다.

### ChatGPT 기능과 권한

- 예약 작업은 ChatGPT Plus 이상이 필요합니다.
- Work, Scheduled, Plugins의 제공 여부는 계정과 워크스페이스 설정에 따라 달라질 수 있습니다.
- GitHub 플러그인의 쓰기 권한이 취소되거나 관리자가 외부 작업을 막으면 리포트 커밋이 실패합니다.
- 예약 작업은 무인 실행이므로 실행 중 추가 승인이 필요한 도구는 중단될 수 있습니다.
- 관련 대화·작업이 일시 중지되거나 플러그인 연결이 만료되면 Scheduled에서 다시 활성화해야 합니다.

### GitHub Actions 사용량

GitHub Free의 비공개 저장소에는 현재 월 2,000분의 표준 runner 사용량이 포함됩니다. 이 workflow는 하루 한 번 실행되지만 실제 사용량은 사이트 응답 시간과 재실행 횟수에 따라 달라집니다. 공개 저장소의 표준 GitHub-hosted runner는 무료이지만, 기사와 리포트도 공개된다는 점을 먼저 고려하세요.

### 60일 비활성화 규칙

GitHub는 **공개 저장소**에 60일 동안 저장소 활동이 없으면 예약 workflow를 자동 비활성화할 수 있습니다. 정상 수집이 매일 커밋되면 보통 활동이 이어지지만, 장기간 멈췄다면 Actions에서 workflow가 활성 상태인지 확인하세요. 이 60일 자동 비활성화 규칙은 GitHub 문서상 공개 저장소에 적용됩니다.

## 문제가 생겼을 때

| 증상 | 확인할 것 |
|---|---|
| Actions가 빨간색 | 실행 로그의 마지막 실패 단계와 `data/candidates-YYYY-MM-DD.json`의 `failures` |
| 후보 파일이 없음 | workflow가 기본 브랜치 `main`에서 실행됐는지, 커밋 권한이 있는지 |
| ChatGPT가 저장소를 못 읽음 | GitHub 플러그인에서 해당 저장소 접근을 허용했는지 |
| 읽기는 되지만 리포트를 못 씀 | 검색용 GitHub 앱만 연결한 것은 아닌지, 플러그인 쓰기 도구가 있는지 |
| `NOT_READY` | 오늘 후보 날짜, Actions conclusion, 수집 성공 55곳 이상 조건 |
| 작업이 실행되지 않음 | Scheduled에서 작업이 Active인지, 다음 실행 시각과 시간대가 맞는지 |

판별 기준이나 수집 대상을 바꾸려면 설치가 정상 동작하는 것을 먼저 확인한 뒤 [CUSTOMIZE.md](CUSTOMIZE.md)를 따라가세요.

## 참고 문서

- [OpenAI Scheduled tasks](https://learn.chatgpt.com/docs/automations?surface=app)
- [OpenAI Plugins](https://learn.chatgpt.com/docs/plugins)
- [OpenAI GitHub 연결의 읽기 전용 범위](https://help.openai.com/en/articles/11145903-connecting-github-to-chatgpt)
- [GitHub 템플릿에서 저장소 만들기](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-repository-from-a-template)
- [GitHub Actions 사용량](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
- [GitHub workflow 활성화와 60일 규칙](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows)
