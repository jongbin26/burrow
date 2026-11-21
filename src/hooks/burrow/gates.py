"""커밋·PR·멈춤 시점에 필요한 스킬이 돌았는지 판정하고, 막을 때 실행할 호출을 알려 준다."""
from __future__ import annotations

from commands import COMMIT, PR_BODY, PR_CREATE
from state import Session

REVIEWER = "burrow-reviewer"

_HOW = {
    "readability-pass": "Skill(skill: \"readability-pass\") — 이번에 건드린 파일마다 책임 한 문장·바뀌는 이유를 판정",
    "pr-slicing": "Skill(skill: \"pr-slicing\") — 이 조각이 PR 문턱을 넘는지, 스택·병렬 중 무엇인지 판정",
    "pr-writing": "Skill(skill: \"pr-writing\") — 원인·하지 않은 선택·확인 못 한 것을 본문에 남기는지 판정",
    REVIEWER: "git diff <base>...HEAD > <scratchpad>/review.diff 를 만든 뒤 Agent(subagent_type: \"burrow-reviewer\", prompt: \"diff: <그 경로>, 합의·거부한 설계: ...\") — 끝날 때까지 기다린 뒤 지적을 반영",
}


def _missing_for(session: Session, action: str) -> list[str]:
    fresh = session.done_since_last_edit
    missing = []
    if action in (COMMIT, PR_CREATE) and not fresh("skill", "readability-pass"):
        missing.append("readability-pass")
    if action == PR_CREATE and not session.has("skill", "pr-slicing"):
        missing.append("pr-slicing")
    if action in (PR_CREATE, PR_BODY) and not session.has("skill", "pr-writing"):
        missing.append("pr-writing")
    if action == PR_CREATE and not fresh("agent", REVIEWER):
        missing.append(REVIEWER)
    return missing


def _message(title: str, missing: list[str]) -> str:
    lines = [f"[burrow] {title}. 아래를 순서대로 실행한 뒤 같은 명령을 다시 실행하라."]
    lines += [f"  {i}. {_HOW[name]}" for i, name in enumerate(missing, 1)]
    lines.append("소스를 다시 고치면 readability-pass 와 burrow-reviewer 는 다시 필요하다.")
    lines.append("사용자만 끌 수 있다: 세션을 BURROW_GATES=off 로 띄우는 경우.")
    return "\n".join(lines)


_TITLES = {COMMIT: "커밋 전 점검이 빠졌다", PR_CREATE: "PR 게시 전 점검이 빠졌다", PR_BODY: "PR 본문 수정 전 점검이 빠졌다"}


def check_command(session: Session, actions: set[str]) -> str | None:
    """막아야 하면 차단 문구, 아니면 None."""
    for action in (PR_CREATE, PR_BODY, COMMIT):
        if action in actions:
            missing = _missing_for(session, action)
            if missing:
                return _message(_TITLES[action], missing)
    return None


def check_stop(session: Session, stop_hook_active: bool, *, mid_task: bool = False) -> str | None:
    """소스를 고친 뒤 readability-pass 없이 멈추려 하면 한 번 막는다. 새 편집이 생겨야 다시 막는다.

    - mid_task: 하위 에이전트가 아직 돌거나 사용자에게 묻고 멈추는 턴. 보고가 아니라 막지 않음
    """
    last_edit = session.last("edit")
    if stop_hook_active or mid_task or last_edit < 0:
        return None
    if session.last("skill", "readability-pass") > last_edit or session.last("block", "stop") > last_edit:
        return None
    session.add("block", "stop")
    return _message("소스를 고친 뒤 끝났다고 보고하기 전 점검이 빠졌다", ["readability-pass"]) + (
        "\n작업 중간에 사용자에게 묻는 것이라면 이 점검 없이 그대로 멈춰도 된다."
    )
