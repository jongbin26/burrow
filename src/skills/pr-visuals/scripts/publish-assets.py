#!/usr/bin/env python3
"""PR·이슈 본문용 그림을 리소스 전용 브랜치에 올리고 본문에 붙일 Markdown을 출력한다.

사용:
  publish-assets.py --asset flow.svg "저장 실패 시 흐름 전후 비교" [--asset ... ] [--for owner/repo]

- 업로드 대상과 허용 목록은 기기별 설정 파일에서 읽는다 (레포에 두지 않음)
  ${XDG_CONFIG_HOME:-~/.config}/pr-assets/config.json
  {"remote": "git@host:owner/assets-repo.git", "branch": "pr-assets", "allow": ["owner/*"]}
- PR을 여는 레포는 현재 디렉토리의 origin 과 --for 로 정한다. 하나라도 allow 에 없으면 아무것도 올리지 않고 exit 3
- 파일은 assets/<sha256>.<확장자> 로 저장하므로 같은 파일을 다시 올려도 같은 주소가 나온다
- 인증은 git 원격 설정(SSH 등)을 그대로 쓴다
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "pr-assets" / "config.json"
CACHE = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "pr-assets"
MARKER = ".pr-assets"
MARKER_TEXT = b"Resource-only branch for PR/issue images. Do not merge.\n"
MAX_FILES, MAX_BYTES = 8, 25 * 1024 * 1024
IMAGE_MAGIC = {".png": [b"\x89PNG\r\n\x1a\n"], ".jpg": [b"\xff\xd8\xff"], ".jpeg": [b"\xff\xd8\xff"],
               ".gif": [b"GIF87a", b"GIF89a"], ".webp": [b"RIFF"]}
LINK_ONLY = {".mp4", ".mov", ".webm", ".html"}
SVG_START = re.compile(rb"^\s*(?:(?:<\?xml[^?]*\?>|<!--.*?-->|<!DOCTYPE\s+svg[^>]*>)\s*)*<svg[\s>/]", re.S)
ASSET_PATH = re.compile(r"^assets/[a-f0-9]{64}\.(png|jpe?g|gif|webp|svg|mp4|mov|webm|html)$")
OWNER_REPO = re.compile(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?/?$")


def fail(code: int, message: str):
    print(f"publish-assets: {message}", file=sys.stderr)
    sys.exit(code)


def owner_repo(remote_url: str) -> str | None:
    m = OWNER_REPO.search(remote_url.strip())
    return f"{m.group(1)}/{m.group(2)}" if m else None


def git(*args: str, cwd: Path, data: bytes | None = None, env: dict | None = None) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, input=data, capture_output=True, env={**os.environ, **(env or {})})
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.decode().strip()}")
    return r.stdout.decode().strip()


def target_repos(extra: list[str]) -> list[str]:
    targets = list(extra)
    try:
        origin = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True, check=True)
        targets.append(owner_repo(origin.stdout) or origin.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    return targets


def check_allowed(config: dict, targets: list[str]) -> None:
    if not targets:
        fail(3, "PR을 여는 레포를 알 수 없다. 그 레포 안에서 실행하거나 --for owner/repo 를 준다")
    allow = config.get("allow") or []
    denied = [t for t in targets if not any(fnmatch.fnmatch(t.lower(), p.lower()) for p in allow)]
    if denied:
        fail(3, f"허용 목록에 없는 레포라 올리지 않는다: {', '.join(denied)}. 그림 대신 본문 텍스트나 mermaid 블록을 쓴다")


def read_asset(path: str) -> tuple[bytes, str]:
    data, ext = Path(path).read_bytes(), Path(path).suffix.lower()
    if ext == ".svg" and SVG_START.match(data) and b"\0" not in data:
        return data, ext
    if ext in IMAGE_MAGIC and any(data.startswith(m) for m in IMAGE_MAGIC[ext]):
        return data, ext
    if ext in LINK_ONLY:
        return data, ext
    fail(2, f"내용과 확장자가 맞는 PNG/JPEG/GIF/WebP/SVG/MP4/MOV/WebM/HTML 만 올린다: {path}")


def cache_repo(remote: str) -> Path:
    repo = CACHE / hashlib.sha1(remote.encode()).hexdigest()[:16]
    if not (repo / "HEAD").exists():
        repo.mkdir(parents=True, exist_ok=True)
        git("init", "--bare", "-q", cwd=repo)
    return repo


def fetch_head(repo: Path, remote: str, branch: str) -> str | None:
    if not git("ls-remote", "--heads", remote, branch, cwd=repo):
        return None
    git("fetch", "-q", "--depth", "1", remote, f"+refs/heads/{branch}:refs/remotes/pr-assets/{branch}", cwd=repo)
    head = git("rev-parse", f"refs/remotes/pr-assets/{branch}", cwd=repo)
    stray = [p for p in git("ls-tree", "-r", "--name-only", head, cwd=repo).splitlines()
             if p != MARKER and not ASSET_PATH.match(p)]
    if stray:
        fail(4, f"{branch} 는 리소스 전용 브랜치가 아니다 (예: {stray[0]}). 설정의 branch 를 바꾼다")
    return head


def commit_assets(repo: Path, head: str | None, files: dict[str, bytes]) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
        if head:
            git("read-tree", head, cwd=repo, env=env)
        for path, data in {**files, MARKER: MARKER_TEXT}.items():
            blob = git("hash-object", "-w", "--stdin", cwd=repo, data=data)
            git("update-index", "--add", "--cacheinfo", f"100644,{blob},{path}", cwd=repo, env=env)
        tree = git("write-tree", cwd=repo, env=env)
    if head and git("rev-parse", f"{head}^{{tree}}", cwd=repo) == tree:
        return head
    parent = ["-p", head] if head else []
    ident = {"GIT_AUTHOR_NAME": "pr-assets", "GIT_AUTHOR_EMAIL": "pr-assets@users.noreply.github.com",
             "GIT_COMMITTER_NAME": "pr-assets", "GIT_COMMITTER_EMAIL": "pr-assets@users.noreply.github.com"}
    return git("commit-tree", tree, *parent, "-m", "Publish PR assets", cwd=repo, env=ident)


def publish(config: dict, files: dict[str, bytes]) -> str:
    remote, branch = config["remote"], config.get("branch", "pr-assets")
    repo = cache_repo(remote)
    for _ in range(3):
        head = fetch_head(repo, remote, branch)
        commit = commit_assets(repo, head, files)
        if commit == head:
            return commit
        try:
            git("push", "-q", remote, f"{commit}:refs/heads/{branch}", cwd=repo)
            return commit
        except RuntimeError:
            continue
    fail(5, "동시 업로드로 브랜치가 계속 바뀌었다. 다시 실행한다")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset", nargs=2, action="append", required=True, metavar=("PATH", "DESCRIPTION"))
    parser.add_argument("--for", dest="targets", action="append", default=[], metavar="OWNER/REPO")
    args = parser.parse_args()
    if not CONFIG.is_file():
        fail(3, f"설정이 없다: {CONFIG}. 사용자가 업로드 대상과 허용 목록을 정해야 한다")
    config = json.loads(CONFIG.read_text())
    check_allowed(config, target_repos(args.targets))
    if len(args.asset) > MAX_FILES:
        fail(2, f"한 번에 {MAX_FILES}개까지 올린다")
    files, links = {}, []
    for path, description in args.asset:
        data, ext = read_asset(path)
        name = f"assets/{hashlib.sha256(data).hexdigest()}{ext}"
        files[name] = data
        links.append((name, ext, description))
    if sum(len(d) for d in files.values()) > MAX_BYTES:
        fail(2, "합계 25 MiB 이하만 올린다")
    commit = publish(config, files)
    web = f"https://github.com/{owner_repo(config['remote'])}"
    for name, ext, description in links:
        label = re.sub(r"[\[\]()<>!`*_\\\r\n]", " ", description).strip()
        if ext in LINK_ONLY:
            print(f"[{label}]({web}/blob/{commit}/{name})")
        else:
            print(f"![{label}]({web}/blob/{commit}/{name}?raw=true)")


if __name__ == "__main__":
    main()
