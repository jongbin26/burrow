#!/usr/bin/env bash
# manifest.txt의 각 항목을 레포 -> 홈 디렉토리 심링크로 건다. 멱등.
#
# 주의: Claude Code 세션을 종료한 뒤 실행할 것. 세션 중에 ~/.claude 하위가 사라지면
# Claude Code가 그 자리에 디렉토리를 다시 만들어 링크 구성이 깨진다.
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
BACKUP="$HOME/.claude-backup-$(date +%Y%m%d%H%M%S)"

[ -f "$MANIFEST" ] || { echo "manifest를 찾을 수 없음: $MANIFEST" >&2; exit 1; }

backed_up=0

# 대상 부모가 ~/.claude면 없을 때 만들고, 다른 도구 홈이면 없을 때 미설치로 본다
ensure_parent() { # $1=부모 절대경로 -> 0=진행 1=건너뜀
  if [ "$1" = "$HOME/.claude" ] || [ "$(dirname "$1")" = "$HOME/.claude" ]; then
    mkdir -p "$1"; return 0
  fi
  [ -d "$1" ] || return 1
  return 0
}

link_one() { # $1=원본 $2=대상 $3=표시이름
  if [ -L "$2" ] && [ "$(readlink "$2")" = "$1" ]; then
    echo "ok     $3"; return
  fi
  if [ -e "$2" ] || [ -L "$2" ]; then
    mkdir -p "$BACKUP/$(dirname "${2#"$HOME"/}")"
    mv "$2" "$BACKUP/${2#"$HOME"/}"
    echo "backup $3 -> $BACKUP/${2#"$HOME"/}"
    backed_up=1
  fi
  ln -sfn "$1" "$2"
  echo "link   $3 -> $1"
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

  # 팬아웃: `skills/*` — 자식을 하나씩 목적지 디렉토리 아래로 링크
  if [ "${item%/\*}" != "$item" ]; then
    base="${item%/\*}"
    src_dir="$REPO/$base"
    dst_dir="$HOME/$dest"

    if [ ! -d "$src_dir" ]; then echo "skip   $item — 레포에 없음"; continue; fi
    if ! ensure_parent "$dst_dir"; then
      echo "skip   $item -> $dest — $dst_dir 없음 (도구 미설치)"; continue
    fi

    for child in "$src_dir"/*; do
      [ -e "$child" ] || continue
      name="$(basename "$child")"
      link_one "$child" "$dst_dir/$name" "$dest/$name"
    done

    # 레포를 가리키는데 대상이 사라진 링크 정리
    for l in "$dst_dir"/*; do
      [ -L "$l" ] || continue
      t="$(readlink "$l")"
      case "$t" in "$src_dir"/*) [ -e "$l" ] || { rm "$l"; echo "prune  $dest/$(basename "$l") — 레포에서 삭제됨"; } ;;
      esac
    done
    continue
  fi

  src="$REPO/$item"
  dst="$HOME/$dest"

  if [ ! -e "$src" ]; then echo "skip   $item -> $dest — 레포에 없음"; continue; fi
  if ! ensure_parent "$(dirname "$dst")"; then
    echo "skip   $item -> $dest — $(dirname "$dst") 없음 (도구 미설치)"; continue
  fi
  link_one "$src" "$dst" "$dest"
done < "$MANIFEST"

if [ "$backed_up" -eq 1 ]; then
  echo
  echo "기존 실체를 백업했다: $BACKUP"
  echo "내용을 확인하고 필요한 것은 레포로 옮긴 뒤 백업 디렉토리를 지울 것."
fi
