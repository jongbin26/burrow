"""멈추는 턴이 사용자에게 묻는 것으로 끝났는지 대화 기록에서 판정한다."""
from __future__ import annotations

import json
from pathlib import Path

_TAIL_BYTES = 200_000
_QUESTION_TOOLS = {"AskUserQuestion"}


def _last_main_assistant(lines: list[str]) -> dict | None:
    for line in reversed(lines):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("type") == "assistant" and not row.get("isSidechain"):
            return row
    return None


def ends_with_question(transcript_path: str) -> bool:
    """마지막 메인 응답 블록이 물음표로 끝나는 글이거나 질문 도구 호출이면 참. 읽지 못하면 거짓"""
    try:
        with Path(transcript_path).open("rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - _TAIL_BYTES))
            lines = f.read().decode("utf-8", "ignore").splitlines()
    except OSError:
        return False
    row = _last_main_assistant(lines)
    blocks = ((row or {}).get("message") or {}).get("content") or []
    if not blocks:
        return False
    last = blocks[-1]
    if last.get("type") == "tool_use":
        return last.get("name") in _QUESTION_TOOLS
    return (last.get("text") or "").rstrip().rstrip("*`)").endswith("?")
