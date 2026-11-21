#!/usr/bin/env python3
"""Claude Code 훅 진입점. stdin 의 이벤트를 기록하고 판정해 JSON 하나를 출력한다.

- 어떤 예외든 출력 없이 exit 0. 깨진 훅이 모든 도구 호출을 막지 않게 하기 위함
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.dont_write_bytecode = True  # 링크된 레포 디렉토리에 캐시를 남기지 않음
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import asset_guard  # noqa: E402
import commands  # noqa: E402
import gates  # noqa: E402
import nudges  # noqa: E402
import turn  # noqa: E402
from paths import is_source  # noqa: E402
from state import Session  # noqa: E402

_SLASH = re.compile(r"^\s*/([\w:-]+)")
_EDIT_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}


def _gates_on() -> bool:
    return os.environ.get("BURROW_GATES", "").lower() not in ("off", "0", "false")


def _context(event: str, text: str | None) -> dict | None:
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}} if text else None


def _skill_name(raw: str) -> str:
    return (raw or "").rsplit(":", 1)[-1]


def _agent_key(data: dict) -> str:
    return f"{data.get('agent_id') or ''}|{data.get('agent_type') or ''}"


def _edit_target(tool_input: dict) -> tuple[str, str]:
    path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    written = tool_input.get("content") or tool_input.get("new_string") or tool_input.get("new_source") or ""
    return path, written


def _pre_tool(session: Session, data: dict) -> dict | None:
    tool, tool_input = data.get("tool_name"), data.get("tool_input") or {}
    if tool == "Bash":
        command = tool_input.get("command", "")
        reason = asset_guard.check(command, data.get("cwd", ""))
        if not reason and _gates_on():
            reason = gates.check_command(session, commands.classify(command))
        if reason:
            return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                           "permissionDecisionReason": reason}}
    if tool in _EDIT_TOOLS:
        path, written = _edit_target(tool_input)
        return _context("PreToolUse", nudges.before_edit(session, path, written, data.get("scratchpad_dir", "")))
    return None


def _post_tool(session: Session, data: dict) -> dict | None:
    tool, tool_input = data.get("tool_name"), data.get("tool_input") or {}
    if tool == "Skill":
        session.add("skill", _skill_name(tool_input.get("skill", "")))
    elif tool in _EDIT_TOOLS:
        path, _ = _edit_target(tool_input)
        scratchpad = data.get("scratchpad_dir", "")
        if is_source(path, scratchpad):
            session.add("edit", path)
        return _context("PostToolUse", nudges.after_edit(session, path, scratchpad))
    return None


def _dispatch(data: dict) -> dict | None:
    event = data.get("hook_event_name")
    session = Session(data.get("session_id", ""))
    if event == "PreToolUse":
        return _pre_tool(session, data)
    if event == "PostToolUse":
        return _post_tool(session, data)
    if event == "SubagentStart":
        session.add("agent-start", _agent_key(data))
    elif event == "SubagentStop":
        session.add("agent-stop", _agent_key(data))
        if data.get("agent_type"):
            session.add("agent", data["agent_type"])
    elif event == "UserPromptSubmit":
        m = _SLASH.match(data.get("prompt") or "")
        if m:
            session.add("skill", _skill_name(m.group(1)))
    elif event == "Stop" and _gates_on():
        mid_task = session.unfinished("agent-start", "agent-stop") > 0 or turn.ends_with_question(
            data.get("transcript_path", ""))
        reason = gates.check_stop(session, bool(data.get("stop_hook_active")), mid_task=mid_task)
        if reason:
            return {"decision": "block", "reason": reason}
    return None


def main() -> None:
    try:
        out = _dispatch(json.load(sys.stdin))
    except Exception:  # noqa: BLE001 — 실패는 통과로
        return
    if out:
        print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
