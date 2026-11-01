#!/usr/bin/env python3
"""디렉토리 README의 `## 파일 지도` 표와 실제 파일을 대조한다. 어긋나면 exit 1.

사용:
  check-file-map.py <dir> [--readme README.md] [--pair .test.ts] [--ignore '.*']

- 표의 첫 칸이 파일명이다. 디렉토리는 `이름/`으로 적는다
- --pair 접미사로 끝나는 파일은 짝 파일로 보고 지도에 없어도 된다
- --ignore 는 fnmatch 패턴. 기본으로 숨김 파일과 README 자체를 거른다
"""
import argparse
import fnmatch
import re
import sys
from pathlib import Path


def mapped_entries(readme: Path) -> set[str] | None:
    if not readme.is_file():
        return None
    text = readme.read_text()
    m = re.search(r"^## 파일 지도\s*$(.*?)(?=^## |\Z)", text, re.S | re.M)
    if not m:
        return None
    entries = set()
    for line in m.group(1).splitlines():
        cell = re.match(r"\|\s*`?([^`|]+?)`?\s*\|", line)
        if not cell:
            continue
        name = cell.group(1).strip()
        if name in ("파일", "---") or name.startswith("-"):
            continue
        entries.add(name)
    return entries


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dir")
    parser.add_argument("--readme", default="README.md")
    parser.add_argument("--pair", action="append", default=[])
    parser.add_argument("--ignore", action="append", default=[".*"])
    args = parser.parse_args()

    root = Path(args.dir)
    readme = root / args.readme
    mapped = mapped_entries(readme)
    if mapped is None:
        print(f"{readme}: '## 파일 지도' 절이 없음")
        sys.exit(1)

    actual = set()
    for child in sorted(root.iterdir()):
        name = child.name + "/" if child.is_dir() else child.name
        if name == args.readme or any(fnmatch.fnmatch(name, p) for p in args.ignore):
            continue
        if not child.is_dir() and any(name.endswith(suffix) for suffix in args.pair):
            continue
        actual.add(name)

    unmapped = sorted(actual - mapped)
    missing = sorted(mapped - actual)
    for name in unmapped:
        print(f"지도에 없음: {root / name}")
    for name in missing:
        print(f"파일이 없음: {root / name} (지도에만 있음)")
    print(f"{root}: 파일 {len(actual)}개, 지도 {len(mapped)}행, 문제 {len(unmapped) + len(missing)}건")
    sys.exit(1 if unmapped or missing else 0)


if __name__ == "__main__":
    main()
