#!/usr/bin/env bash
# manifest 항목의 링크 무결성 점검. 이상이 있으면 exit 1.
set -euo pipefail

self="${BASH_SOURCE[0]}"
while [ -L "$self" ]; do
  self_dir="$(cd -P "$(dirname "$self")" && pwd)"
  self="$(readlink "$self")"
  case "$self" in /*) ;; *) self="$self_dir/$self" ;; esac
done
SCRIPT_DIR="$(cd -P "$(dirname "$self")" && pwd)"
REPO="${CLAUDE_CONFIG_REPO:-$(dirname "$SCRIPT_DIR")}"
MANIFEST="$REPO/manifest.txt"

[ -f "$MANIFEST" ] || { echo "manifest를 찾을 수 없음: $MANIFEST" >&2; exit 1; }

problems=0
checked=0
missing=0

check_one() { # $1=기대원본 $2=대상 $3=표시이름
  checked=$((checked+1))
  if [ -L "$2" ]; then
    t="$(readlink "$2")"
    if [ ! -e "$2" ]; then echo "DANGLING $2 — 대상 없음 ($t)"; problems=1
    elif [ "$t" != "$1" ]; then echo "WRONG    $2 — $t 을 가리킴 (기대: $1)"; problems=1
    else echo "ok       $3"; fi
  elif [ -e "$2" ]; then
    echo "BROKEN   $2 — 링크가 실파일로 대체됨"; problems=1
  else
    echo "MISSING  $2"; problems=1; missing=$((missing+1))
  fi
}

while IFS= read -r raw || [ -n "$raw" ]; do
  line="$(echo "${raw%%#*}" | xargs)"
  [ -n "$line" ] || continue

  case "$line" in
    *"->"*) item="$(echo "${line%%->*}" | xargs)"; dest="$(echo "${line#*->}" | xargs)" ;;
    *)      item="$line"; dest=".claude/$(basename "$line")" ;;
  esac
  dest="${dest%/}"
  case "$item" in *"/*") ;; *) item="${item%/}" ;; esac

  if [ "${item%/\*}" != "$item" ]; then
    base="${item%/\*}"; src_dir="$REPO/$base"; dst_dir="$HOME/$dest"
    if [ "$(dirname "$dst_dir")" != "$HOME/.claude" ] && [ ! -d "$(dirname "$dst_dir")" ]; then
      echo "skip     $dest — $(dirname "$dst_dir") 없음 (도구 미설치)"; continue
    fi
    for child in "$src_dir"/*; do
      [ -e "$child" ] || continue
      check_one "$child" "$dst_dir/$(basename "$child")" "$dest/$(basename "$child")"
    done
    # 레포를 가리키는데 대상이 사라진 링크
    for l in "$dst_dir"/*; do
      [ -L "$l" ] || continue
      t="$(readlink "$l")"
      case "$t" in "$src_dir"/*) [ -e "$l" ] || { echo "STALE    $l — 레포에서 삭제된 항목"; problems=1; } ;;
      esac
    done
    continue
  fi

  src="$REPO/$item"; dst="$HOME/$dest"
  if [ "$(dirname "$dst")" != "$HOME/.claude" ] && [ ! -d "$(dirname "$dst")" ]; then
    echo "skip     $dest — $(dirname "$dst") 없음 (도구 미설치)"; continue
  fi
  check_one "$src" "$dst" "$dest"
done < "$MANIFEST"

if [ "$checked" -gt 0 ] && [ "$missing" -eq "$checked" ]; then
  echo
  echo "링크가 하나도 없다 — 클론 직후로 보인다."
  echo "  1) $REPO/bin/link.sh 실행"
  echo "  2) 도구 재시작 (스킬은 시작 시 로드된다)"
  echo "  3) README 의 '새 기기 체크리스트' 확인 (settings.json·플러그인은 이 레포가 관리하지 않는다)"
fi

exit "$problems"
