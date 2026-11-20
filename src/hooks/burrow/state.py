"""세션별 사건 기록. 한 줄에 사건 하나, 줄 순서가 곧 시간 순서다."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path


def _state_dir() -> Path:
    base = os.environ.get("BURROW_STATE_DIR") or os.path.join(os.path.expanduser("~"), ".local", "state", "burrow")
    return Path(base)


class Session:
    def __init__(self, session_id: str):
        safe = re.sub(r"[^A-Za-z0-9_-]", "_", session_id or "unknown")
        self.path = _state_dir() / f"{safe}.jsonl"
        self._events = None

    @property
    def events(self) -> list:
        if self._events is None:
            self._events = []
            if self.path.is_file():
                for line in self.path.read_text().splitlines():
                    try:
                        self._events.append(json.loads(line))
                    except ValueError:
                        continue
        return self._events

    def add(self, kind: str, name: str) -> None:
        event = {"kind": kind, "name": name}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        self.events.append(event)

    def last(self, kind: str, name: str | None = None) -> int:
        """마지막으로 일어난 위치. 없으면 -1."""
        for i in range(len(self.events) - 1, -1, -1):
            e = self.events[i]
            if e["kind"] == kind and (name is None or e["name"] == name):
                return i
        return -1

    def has(self, kind: str, name: str) -> bool:
        return self.last(kind, name) >= 0

    def done_since_last_edit(self, kind: str, name: str) -> bool:
        """편집이 없던 세션이면 한 번이라도 했는지만 본다."""
        return self.last(kind, name) > self.last("edit")
