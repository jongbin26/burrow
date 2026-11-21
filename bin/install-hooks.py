#!/usr/bin/env python3
"""burrow 훅을 이 기기의 ~/.claude/settings.json 에 병합한다. 멱등.

settings.json 은 기기별 설정이라 레포가 소유하지 않는다. 이 스크립트는 burrow 훅 항목만
넣고 빼며, 다른 훅과 설정은 건드리지 않는다. 쓰기 전에 같은 디렉토리에 백업을 남긴다.

사용:
  bin/install-hooks.py            # 등록 (이미 있으면 갱신)
  bin/install-hooks.py --remove   # burrow 항목만 제거
"""
import argparse
import json
import shutil
import time
from pathlib import Path

SETTINGS = Path.home() / ".claude" / "settings.json"
COMMAND = "python3 \"$HOME/.claude/hooks/burrow/hook.py\""
MARK = ".claude/hooks/burrow/hook.py"

# (이벤트, matcher). matcher 가 None 이면 matcher 없는 이벤트
REGISTRATIONS = [
    ("PreToolUse", "Bash|Write|Edit|MultiEdit|NotebookEdit"),
    ("PostToolUse", "Skill|Write|Edit|MultiEdit|NotebookEdit"),
    ("SubagentStart", None),
    ("SubagentStop", None),
    ("UserPromptSubmit", None),
    ("Stop", None),
]


def strip(hooks: dict) -> None:
    for event in list(hooks):
        groups = [g for g in hooks[event] if not any(MARK in h.get("command", "") for h in g.get("hooks", []))]
        if groups:
            hooks[event] = groups
        else:
            del hooks[event]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--remove", action="store_true")
    args = parser.parse_args()

    settings = json.loads(SETTINGS.read_text()) if SETTINGS.is_file() else {}
    hooks = settings.setdefault("hooks", {})
    strip(hooks)
    if not args.remove:
        for event, matcher in REGISTRATIONS:
            group = {"hooks": [{"type": "command", "command": COMMAND, "timeout": 10}]}
            if matcher:
                group = {"matcher": matcher, **group}
            hooks.setdefault(event, []).append(group)

    if SETTINGS.is_file():
        backup = SETTINGS.with_name(f"settings.json.burrow-backup-{time.strftime('%Y%m%d%H%M%S')}")
        shutil.copy2(SETTINGS, backup)
        print(f"backup {backup}")
    SETTINGS.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n")
    print("removed" if args.remove else f"registered {len(REGISTRATIONS)} events -> {COMMAND}")


if __name__ == "__main__":
    main()
