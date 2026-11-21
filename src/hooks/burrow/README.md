# burrow 훅

Claude Code 훅으로 burrow 스킬을 작업 흐름에 끼워 넣는다. `$HOME/.claude/hooks/burrow` 로 링크되고,
등록은 기기마다 `bin/install-hooks.py` 가 `~/.claude/settings.json` 에 병합한다.

| 단계 | 시점 | 하는 일 |
|---|---|---|
| 1 | `git commit`, `gh pr create`·`gh stack`, `gh pr edit --body`, 세션 멈춤 | 필요한 스킬이 이 세션에서 안 불렸으면 막고 실행할 호출을 알려 줌 |
| 2 | 새 파일, 공개 계약 파일, 테스트 파일 편집, 200줄 초과 | 해당 스킬을 열라는 문맥을 한 번 주입 |
| 3 | PR 생성 | `burrow-reviewer` 에이전트가 마지막 편집 뒤에 끝났는지 확인 |

- 스크립트 오류는 언제나 통과로 처리. 깨진 PreToolUse 훅은 모든 셸 호출을 막기 때문
- `BURROW_GATES=off` 환경변수로 띄운 세션은 스킬 차단 없이 기록과 주입만 함. 그림 주소 차단(`asset_guard.py`)은 꺼지지 않음
- 기록은 `${BURROW_STATE_DIR:-$HOME/.local/state/burrow}/<session_id>.jsonl`

## 파일 지도

| 파일 | 책임 |
|---|---|
| `hook.py` | 훅 진입점. 이벤트별로 기록·판정을 호출하고 출력 JSON을 만듦 |
| `state.py` | 세션별 사건 기록(스킬·에이전트·편집·주입·차단)과 순서 조회 |
| `commands.py` | 셸 명령에서 커밋·PR 게시 동작을 판별 |
| `gates.py` | 커밋·PR·멈춤 시점의 차단 판정과 차단 문구 |
| `nudges.py` | 편집 대상에 맞는 스킬 문맥 주입 판정 |
| `asset_guard.py` | 허용하지 않은 레포의 PR·이슈에 개인 리소스 레포 그림 주소가 실리는 것을 막음 |
| `paths.py` | 경로가 소스·테스트·공개 계약인지 분류 |
