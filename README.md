# burrow

에이전트 CLI 전역 설정의 형상관리 레포. **레포가 실제 파일을 소유하고**, 각 도구의 홈
디렉토리에는 심링크만 둔다. 동기화 명령 없이 `git pull` 만으로 반영된다.

**레포 위치는 자유다.** `bin/link.sh`와 `bin/doctor.sh`는 자기 파일 위치에서 레포 루트를
유도하므로 어디에 클론하든 그대로 동작한다. 아래에서는 클론한 경로를 `$REPO`로 쓴다.
다른 곳을 가리키게 하려면 `CLAUDE_CONFIG_REPO` 환경변수로 덮어쓴다.

## 원칙: 환경과 독립적일 것

레포 내용은 **레포 안에서 완결되어야 한다.** 경로를 박지 않고, 외부 자료가 근거면 인용문을 옮겨 적고,
도구 설정(`settings.json`)처럼 기기마다 달라지는 값은 관리하지 않는다. 지켜야 할 항목은 `CLAUDE.md`에 있다.

## 구조

**뿌릴 것과 레포 문서를 위치로 가른다.** `src/` 아래가 홈 디렉토리로 링크될 내용이고,
루트의 문서는 이 레포를 다룰 때 읽는 것이다.

```
$REPO/                        ← 진실. git이 여기만 추적
├── CLAUDE.md                 ← 이 레포에서 작업할 때의 규칙
├── AGENTS.md                 → CLAUDE.md (다른 도구도 같은 규칙을 읽는다)
├── README.md
├── manifest.txt
├── bin/
│   ├── link.sh
│   ├── doctor.sh
│   ├── lint-skills.py        ← 스킬 정적 점검
│   └── eval-triggers.py      ← 스킬 자동 호출 eval
├── evals/triggers.json       ← eval 케이스
└── src/                      ← 홈으로 링크될 원본
    ├── AGENTS.md             ← 전역 개인 지침
    ├── agents/
    ├── skills/               ← 이 레포가 만든 스킬만 있다
    └── dev-core/             ← 개발 지식 스킬. skills/ 와 같은 목적지로 링크

~/.claude/                    ← Claude Code가 읽는 곳
├── CLAUDE.md      → $REPO/src/AGENTS.md
├── agents/        → $REPO/src/agents/
├── skills/        (실제 디렉토리 — 아래 항목만 링크)
│   ├── pr-writing/        → $REPO/src/skills/pr-writing/
│   ├── root-cause/        → $REPO/src/dev-core/root-cause/
│   ├── ...
│   └── peon-ping-log/     (플러그인이 만든 것. 건드리지 않는다)
├── projects/      (실제 디렉토리, 로컬 전용 — 건드리지 말 것)
├── history.jsonl  (실제 파일, 로컬 전용 — 건드리지 말 것)
└── ...

~/.agents/skills/             ← Codex 개인 스킬 (실제 디렉토리, 항목별 링크)
├── pr-writing/               → $REPO/src/skills/pr-writing/
└── ...

~/.codex/AGENTS.md            → $REPO/src/AGENTS.md
~/.gemini/GEMINI.md           → $REPO/src/AGENTS.md
~/.config/opencode/AGENTS.md  → $REPO/src/AGENTS.md
```

**루트 `CLAUDE.md`와 `src/AGENTS.md`를 혼동하지 말 것.** 루트는 이 레포를 고칠 때의 규칙이고,
`src/AGENTS.md`는 모든 프로젝트에서 로드되는 개인 지침이다. 루트의 `AGENTS.md`는 `CLAUDE.md`를
가리키는 심링크라, 어느 도구로 이 레포를 열어도 같은 규칙을 읽는다.

도구 홈 자체는 링크하지 않는다. 트랜스크립트·히스토리·캐시 같은 앱 데이터가 거기 살아야 하기
때문이다. `manifest.txt`에 적힌 항목만 링크한다.

## 전역 지침을 한 파일로

도구마다 전역 지침 파일의 이름과 위치가 다르다. `AGENTS.md` 하나만 두고 각 도구가
기대하는 이름으로 링크를 건다. 한 곳을 고치면 전부 따라온다.

| 도구 | 읽는 경로 |
|---|---|
| Claude Code | `~/.claude/CLAUDE.md` |
| Codex CLI | `~/.codex/AGENTS.md` |
| Gemini CLI | `~/.gemini/GEMINI.md` |
| opencode | `~/.config/opencode/AGENTS.md` |

그래서 `src/AGENTS.md`에는 **도구 중립적인 상시 규칙만 쓴다.** 요청 시 필요한 절차는
`src/skills/`와 `src/dev-core/`에 두고 Claude Code와 Codex에 같은 원본을 링크한다.

Cursor는 전역 지침 파일 규약이 없어(프로젝트의 `.cursor/rules`를 쓴다) 목록에서 제외했다.

## manifest.txt

한 줄에 한 항목. `출처` 또는 `출처 -> 목적지` 형식이다.

- **출처** — 이 레포 기준 상대 경로
- **목적지** — `$HOME` 기준 상대 경로. 생략하면 `.claude/<출처의 파일명>`

출처가 `/*`로 끝나면 **팬아웃**이다 — 그 디렉토리의 자식을 하나씩 목적지 아래로 링크한다.
목적지 디렉토리는 실디렉토리로 남아, 플러그인이 만든 이웃을 건드리지 않는다.

```
src/skills/* -> .claude/skills/
src/skills/* -> .agents/skills/
src/dev-core/* -> .claude/skills/
src/dev-core/* -> .agents/skills/
```

목적지의 부모 디렉토리(도구 홈)가 없으면 해당 도구 미설치로 보고 건너뛴다. 그래서
Gemini를 안 쓰는 기기에서도 같은 manifest가 그대로 돈다.

## 최초 세팅

```sh
git clone <레포 URL> ~/burrow   # 경로는 원하는 대로
~/burrow/bin/link.sh
```

> **최초 세팅은 도구 세션을 종료한 뒤 실행할 것.** 기존 실체를 백업으로 치우는 단계라,
> 세션이 살아 있으면 도구가 그 자리를 다시 만들어 링크가 깨질 수 있다. 출력의 `backup` 줄이
> 그 단계를 뜻한다.
>
> 세팅이 끝난 뒤 **새 항목만 추가할 때는 세션 중에 실행해도 된다** — 링크만 만들고 아무것도
> 치우지 않는다. 다만 스킬은 세션 재시작 전까지 로드되지 않는다.

`link.sh`는 멱등하다. 이미 올바른 링크면 `ok`만 출력하고 지나간다. 기존 실체가 있으면
지우지 않고 `~/.claude-backup-<타임스탬프>/`로 옮긴 뒤 링크를 건다.

세팅 직후에는 아래 **새 기기 체크리스트**를 확인할 것. 클론+링크만으로는 끝나지 않는다.

## 일상 워크플로

파일은 도구 홈 쪽에서 고치든 레포에서 고치든 같은 실체다. 편한 쪽에서 고치고 레포에서
커밋한다.

```sh
cd $REPO
git diff
git commit -am "..."
git push
```

다른 기기는 `git pull` 만 하면 된다. 링크가 이미 걸려 있으므로 추가 동작이 없다.

## 새 항목 추가

1. 레포에 파일/디렉토리를 만든다
2. `manifest.txt`에 한 줄 추가한다
3. `link.sh`를 다시 실행한다 (기존 링크는 `ok`로 통과)

디렉토리째 링크된 항목(`agents/`)은 안에 파일을 더해도 아무것도 안 해도 된다.
**`skills/`와 `dev-core/`는 팬아웃이라 새 스킬을 추가하면 `link.sh`를 다시 돌려야 한다.** 잊어도 `doctor.sh`가
`MISSING`으로 알려준다.

공유 스킬은 **항목 단위로 링크한다.** 두 도구의 스킬 디렉토리를 실제 디렉토리로 유지해
외부 설치물이 만든 이웃을 보존한다.

## doctor.sh

링크 무결성을 점검한다. 이상이 있으면 exit 1.

```sh
$REPO/bin/doctor.sh
```

| 상태 | 의미 |
|---|---|
| `BROKEN` | 링크가 있어야 할 자리에 실파일이 있음 |
| `MISSING` | 아무것도 없음 |
| `DANGLING` | 심링크인데 대상이 없음 |
| `WRONG` | 심링크인데 엉뚱한 곳을 가리킴 |
| `STALE` | 레포에서 지운 항목의 링크가 남음 (`link.sh`가 정리한다) |
| `skip` | 도구가 설치되지 않음 (이상 아님) |

### BROKEN이 생기는 이유

프로그램이 임시 파일에 쓰고 rename 하는 방식(atomic write)으로 저장하면 심링크가
일반 파일로 교체된다. **도구가 스스로 덮어쓰는 파일은 링크 대상으로 두지 않는다** —
`settings.json`을 관리하지 않는 이유가 이것이다. 디렉토리 링크는 안전하다.

대응: 실파일 내용을 레포로 옮기고 `link.sh`를 다시 돌리거나, 해당 항목을
`manifest.txt`에서 빼고 복사로 관리한다.

## 스킬 검증

스킬은 description만 보고 자동 호출되므로, 문구를 고치면 엉뚱한 스킬이 불리거나 아무것도 안 불릴 수 있다.
두 층으로 확인한다.

```sh
$REPO/bin/lint-skills.py       # 모델 호출 없음. 스킬을 고칠 때마다
$REPO/bin/eval-triggers.py     # 실제 모델 호출. description을 고쳤을 때
```

**`lint-skills.py`** — frontmatter `name`과 디렉토리명 일치, description 길이, description이 언급한
스킬이 실제로 있는지, dev-core 형식(원칙 7개 이하, 판정 질문 두 개 이하, 예시 3줄 이내, 위반 신호 절)을 본다.

**`eval-triggers.py`** — `evals/triggers.json`의 발화를 Claude Code와 Codex에 똑같이 넣고, 어떤 스킬이
불렸는지 채점한다. 케이스마다 정답 `expect`(이 중 하나가 불려야 함)를 달고, 같이 불려도 정당한 스킬만 `ok`에 둔다.
그 밖의 레포 스킬이 불리면 오답이다. 불리면 안 되는 스킬을 따로 나열하지 않으므로 예상 못 한 오호출도 잡힌다.
결과로 케이스별 통과, 스킬별 recall(불려야 할 때 불림)·precision(불렸을 때 맞음), 오답 목록을 낸다.

| 에이전트 | 실행 | 호출 판정 | 격리 |
|---|---|---|---|
| Claude Code | `claude plugin eval` (src 스킬을 임시 플러그인으로 묶음) | trace의 `Skill` tool_use 입력 | 플러그인 eval 샌드박스. 개인 CLAUDE.md·설정·다른 플러그인 없음 |
| Codex | `codex exec --json -s read-only` | `.agents/skills/<name>/SKILL.md`를 읽는 `command_execution` | 임시 `HOME`·`CODEX_HOME`. `auth.json`만 복사하고 끝나면 삭제 |

- 케이스당 기본 1회. 확률적이라 description을 확정할 때는 `--runs 3`
- 비용은 Claude 쪽이 케이스당 약 $0.1. `--max-cost-usd`(기본 5)로 상한을 건다
- `E1`은 실행 자체가 실패한 회차다. 호출 안 됨과 구분한다
- Codex 설치본이 여러 개면 `CODEX_BIN=<경로>`로 지정한다
- 실패하면 케이스가 모호한지 description이 겹치는지 먼저 가른다. 케이스가 모호하면 `expect`나 `ok`를 넓히고,
  description이 겹치면 해당 스킬을 고친다
- 새 스킬을 만들면 호출돼야 할 발화와 비슷하지만 다른 스킬이어야 할 발화를 하나씩 추가한다

## 레포에 넣지 않는 것

앱 데이터와 머신 전용 상태는 추적하지 않는다. 특히 **트랜스크립트는 평문이라 `.env`
값 같은 시크릿이 들어있을 수 있다.**

`~/.claude.json`, `projects/`, `history.jsonl`, `file-history/`, `plans/`, `debug/`,
`paste-cache/`, `image-cache/`, `session-env/`, `tasks/`, `shell-snapshots/`,
`backups/`, `sessions/`, `usage-data/`, `stats-cache.json`, `plugins/`

**`settings.json`·`settings.local.json`도 제외한다.** 훅·statusLine은 외부 설치물 경로에
매달려 있고, 플러그인 목록은 마켓플레이스 접근 권한에 따라 달라지며, 도구가 스스로 덮어쓴다.
기기마다 `/config`로 맞추는 편이 맞다.

새 기기에서 손으로 되살릴 만한 개인 선호는 다음 정도다 — `model`, `theme`(색각 보정),
`effortLevel`, `advisorModel`, `tui`.

### 외부 설치물

플러그인·인스톨러가 만든 스킬·훅은 **이 레포에 들어오지 않는다.** `skills/`를 통째로 링크하지 않고
항목 단위로 링크하기 때문에, `~/.claude/skills`와 `~/.agents/skills`는 실디렉토리로 남고
남의 것은 그 자리에 그대로 있다.
그래서 `.gitignore`에 남의 것을 나열할 필요가 없다.

## 새 기기 체크리스트

클론 + `link.sh` 이후 추가로 필요한 것들. 전부 이 레포 바깥이 소유한 상태다.

- **`settings.json` 재구성.** 플러그인·마켓플레이스·훅·statusLine·개인 선호를 그 기기에서
  다시 잡는다. 이 레포는 관여하지 않는다.
- **외부 스킬 인스톨러 재실행.** 이 레포가 소유하지 않는 스킬은 별도로 설치한다.

## 주의

- **레포는 private으로 둘 것.** 개인 지침과 업무 맥락이 담긴 스킬이 들어 있다.
- Windows는 심링크 생성에 관리자 권한 또는 개발자 모드가 필요하다(WSL이면 무관).
- 훅에 절대 경로를 박지 말 것. `$HOME/.claude/hooks/x.sh` 형태를 쓴다.
- 개인/회사 계정을 한 기기에서 같이 쓴다면 `~/.ssh/config`에 Host 별칭을 두고 **양쪽 블록에
  `IdentitiesOnly yes`를 넣을 것.** 없으면 ssh-agent에 먼저 올라간 키가 제시돼 의도하지 않은
  계정으로 인증된다. 클론 URL은 그 별칭을 쓰고, 레포에 `git config user.email`을 따로 잡는다.
