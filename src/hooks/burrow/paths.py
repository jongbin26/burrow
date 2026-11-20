"""경로 분류. 편집 기록과 문맥 주입이 같은 기준을 쓰도록 한곳에 둔다."""
from __future__ import annotations

import re

SOURCE_EXT = re.compile(r"\.(tsx?|jsx?|mjs|cjs|py|go|rs|java|kt|swift|rb|sh|css|scss|vue|svelte)$")
TEST = re.compile(r"(\.(test|spec)\.[a-z]+$)|(/__tests__/)|(/tests?/test_[^/]+\.py$)")
# 다른 모듈이 기대는 모양이 정해지는 파일
CONTRACT = re.compile(
    r"(/_facade/)|(/index\.(ts|tsx|js|mjs)$)|(/package\.json$)|(protocol[^/]*$)|(\.d\.ts$)|(contract[^/]*$)"
)
# 에이전트 작업 공간·메모리는 작업 산출물이 아님
SCRATCH = re.compile(r"(/scratchpad/)|(^/tmp/)|(^/private/tmp/)|(/\.claude/projects/)")


def is_source(path: str, scratchpad: str = "") -> bool:
    if not path or SCRATCH.search(path) or (scratchpad and path.startswith(scratchpad)):
        return False
    return bool(SOURCE_EXT.search(path))


def is_test(path: str) -> bool:
    return bool(TEST.search(path or ""))


def is_contract(path: str) -> bool:
    return bool(CONTRACT.search(path or ""))
