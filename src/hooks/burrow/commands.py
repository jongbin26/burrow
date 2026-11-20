"""셸 명령에서 커밋과 PR 게시를 골라낸다. 따옴표·heredoc 안의 글자는 명령으로 보지 않는다."""
from __future__ import annotations

import re
import shlex

COMMIT = "commit"
PR_CREATE = "pr-create"
PR_BODY = "pr-body"

_HEREDOC = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n.*?\n\s*\1\s*(?=\n|$)", re.S)
_QUOTED = re.compile(r"'[^']*'|\"(?:[^\"\\]|\\.)*\"")
_SEPARATOR = re.compile(r"\|\||&&|[;|&\n()]")
_ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_PREFIXES = {"sudo", "command", "exec", "env", "time", "nohup"}
_GIT_OPTS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}
_BODY_FLAGS = {"--body", "-b", "--body-file", "-F"}


def _segments(command: str) -> list[list[str]]:
    text = _QUOTED.sub("''", _HEREDOC.sub("", command))
    out = []
    for part in _SEPARATOR.split(text):
        try:
            words = shlex.split(part)
        except ValueError:
            words = part.split()
        while words and (_ENV_ASSIGN.match(words[0]) or words[0] in _PREFIXES):
            words = words[1:]
        if words:
            out.append(words)
    return out


def _git_subcommand(args: list[str]) -> str:
    i = 0
    while i < len(args):
        a = args[i]
        if a in _GIT_OPTS_WITH_VALUE:
            i += 2
        elif a.startswith("-"):
            i += 1
        else:
            return a
    return ""


def _has_flag(args: list[str], flags: set[str]) -> bool:
    return any(a in flags or a.split("=", 1)[0] in flags for a in args)


def classify(command: str) -> set[str]:
    actions = set()
    for words in _segments(command or ""):
        tool, args = words[0].rsplit("/", 1)[-1], words[1:]
        if tool == "git" and _git_subcommand(args) == "commit":
            actions.add(COMMIT)
        elif tool == "gh" and args[:2] == ["pr", "create"]:
            actions.add(PR_CREATE)
        elif tool == "gh" and args[:1] == ["stack"] and args[1:2] in (["submit"], ["create"], ["push"]):
            actions.add(PR_CREATE)
        elif tool == "gh" and args[:2] == ["pr", "edit"] and _has_flag(args, _BODY_FLAGS):
            actions.add(PR_BODY)
    return actions
