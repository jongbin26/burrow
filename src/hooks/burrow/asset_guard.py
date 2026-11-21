"""허용하지 않은 레포의 PR·이슈에 개인 리소스 레포 그림 주소가 실리는 것을 막는다.

- 설정은 pr-visuals 업로드 스크립트와 같은 파일을 읽는다. 설정이 없으면 판정하지 않음
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import shlex
import subprocess
from pathlib import Path

from commands import segments

_OWNER_REPO = re.compile(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?/?$")
_BODY_FILE_FLAGS = {"--body-file", "-F"}
_REPO_FLAGS = {"--repo", "-R"}


def _config() -> dict | None:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    path = base / "pr-assets" / "config.json"
    return json.loads(path.read_text()) if path.is_file() else None


def _owner_repo(url: str) -> str | None:
    m = _OWNER_REPO.search(url.strip())
    return f"{m.group(1)}/{m.group(2)}" if m else None


def _flag_values(words: list[str], flags: set[str]) -> list[str]:
    values = []
    for i, w in enumerate(words):
        name, _, inline = w.partition("=")
        if name in flags:
            values.append(inline or (words[i + 1] if i + 1 < len(words) else ""))
    return [v for v in values if v]


def _target(words: list[str], cwd: str) -> str | None:
    explicit = _flag_values(words, _REPO_FLAGS)
    if explicit:
        return _owner_repo("/" + explicit[0]) or explicit[0]
    r = subprocess.run(["git", "-C", cwd or ".", "remote", "get-url", "origin"], capture_output=True, text=True)
    return _owner_repo(r.stdout) if r.returncode == 0 else None


def _text_sent(command: str, words: list[str], cwd: str) -> str:
    text = command
    for path in _flag_values(words, _BODY_FILE_FLAGS):
        file = Path(cwd or ".", path).expanduser()
        if path != "-" and file.is_file():
            text += "\n" + file.read_text(errors="ignore")
    return text


def check(command: str, cwd: str) -> str | None:
    """막아야 하면 차단 문구, 아니면 None."""
    config = _config()
    if not config or not any(w and w[0].rsplit("/", 1)[-1] == "gh" for w in segments(command)):
        return None
    dest = _owner_repo(config.get("remote", ""))
    try:
        words = shlex.split(command)
    except ValueError:
        words = command.split()
    pattern = re.compile(rf"(github\.com|raw\.githubusercontent\.com)/{re.escape(dest or '')}/", re.I)
    if not dest or not pattern.search(_text_sent(command, words, cwd)):
        return None
    target = _target(words, cwd)
    allow = config.get("allow") or []
    if target and any(fnmatch.fnmatch(target.lower(), p.lower()) for p in allow):
        return None
    return (
        f"[burrow] {target or '알 수 없는 레포'} 는 그림 업로드 허용 목록에 없다. "
        f"{dest} 의 그림 주소를 이 레포의 PR·이슈에 싣지 않는다.\n"
        "그림 주소를 빼고 본문 텍스트·표·mermaid 블록으로 다시 쓴 뒤 실행하라. 허용 목록은 사용자만 바꾼다."
    )
