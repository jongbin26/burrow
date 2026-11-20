"""편집 대상에 맞는 스킬을 열라는 문맥을 고른다. 세션당 스킬 하나에 한 번만 주입한다."""
from __future__ import annotations

import os
import re

from paths import is_contract, is_source, is_test
from state import Session

LINE_LIMIT = 200

_WHY = {
    "file-map": "새 파일의 자리를 디렉토리 README 파일 지도에서 먼저 가리킨다",
    "module-boundaries": "이 코드를 어느 모듈·레이어에 둘지, 의존 방향을 판정한다",
    "abstraction": "새 레이어가 지금 필요한지, 이름이 하는 일을 말하는지 판정한다",
    "type-modeling": "공개 계약의 상태·결과·실패 모양을 판정한다",
    "change-scope": "계약 변경을 additive하게, 되돌릴 수 있게 넣는지 판정한다",
    "design-fidelity": "최신 합의와 거부한 구조가 계약에 남았는지 확인한다",
    "write-test-code": "계약 중심 케이스와 목 수준을 정한다",
    "cohesion": f"{LINE_LIMIT}줄을 넘었다. 바뀌는 이유가 둘 이상인지 판정한다",
    "typescript": "판별 유니온·경계 parse·단언 기준을 본다",
    "react": "상태 위치·리렌더 범위·useEffect 무게를 본다",
    "effect": "실행 경계·에러 채널·Layer 주입을 본다",
    "rxjs": "구독 해제 책임·고차 연산자의 동시성 정책을 본다",
}

_EFFECT = re.compile(r"""from\s+['"]effect(/[^'"]*)?['"]""")
_RXJS = re.compile(r"""from\s+['"]rxjs(/[^'"]*)?['"]""")


def _candidates_before(path: str, written: str, scratchpad: str) -> list[str]:
    skills = []
    if is_contract(path):
        skills += ["type-modeling", "change-scope", "design-fidelity"]
    if not is_source(path, scratchpad):
        return skills
    if is_test(path):
        skills.append("write-test-code")
    elif not os.path.exists(path):
        skills += ["file-map", "module-boundaries", "abstraction"]
    if re.search(r"\.tsx?$", path):
        skills.append("typescript")
    if path.endswith(".tsx"):
        skills.append("react")
    if _EFFECT.search(written):
        skills.append("effect")
    if _RXJS.search(written):
        skills.append("rxjs")
    return skills


def _line_count(path: str) -> int:
    try:
        with open(path, "rb") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def _render(session: Session, skills: list[str], path: str) -> str | None:
    fresh = [s for s in dict.fromkeys(skills) if not session.has("skill", s) and not session.has("nudge", s)]
    if not fresh:
        return None
    for s in fresh:
        session.add("nudge", s)
    lines = [f"[burrow] {os.path.basename(path)} 편집 전에 아래 스킬 본문을 Skill 도구로 열고 판정 질문에 답하라."]
    lines += [f"  - Skill(skill: \"{s}\") — {_WHY[s]}" for s in fresh]
    return "\n".join(lines)


def before_edit(session: Session, path: str, written: str, scratchpad: str = "") -> str | None:
    return _render(session, _candidates_before(path, written, scratchpad), path)


def after_edit(session: Session, path: str, scratchpad: str = "") -> str | None:
    if not is_source(path, scratchpad) or session.has("nudge", f"lines:{path}"):
        return None
    if _line_count(path) <= LINE_LIMIT:
        return None
    session.add("nudge", f"lines:{path}")
    if session.has("skill", "cohesion"):
        return f"[burrow] {os.path.basename(path)} 가 {LINE_LIMIT}줄을 넘었다. cohesion 판정 질문으로 다시 가른다."
    return _render(session, ["cohesion"], path)
