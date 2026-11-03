#!/usr/bin/env python3
"""스킬 자동 호출 eval. evals/triggers.json 의 케이스를 Claude Code·Codex 에 돌려 호출된 스킬을 채점한다.

사용:
  bin/eval-triggers.py                       # 두 에이전트, 케이스당 1회
  bin/eval-triggers.py --agent claude --runs 3 --case 'root-cause-*'
  bin/eval-triggers.py --agent codex --codex-model gpt-5.5
  CODEX_BIN=/opt/homebrew/bin/codex bin/eval-triggers.py --agent codex

채점: expect 중 하나가 불리고, expect·ok 밖의 레포 스킬은 하나도 불리지 않아야 통과.
레포 밖 스킬(도구 내장 등)은 채점하지 않는다. 스킬별 precision·recall 과 오호출 목록을 함께 낸다.

모든 실행은 실제 모델 호출이라 비용이 든다. 실패 케이스가 하나라도 있으면 exit 1.
"""
import argparse
import contextlib
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(os.environ.get("CLAUDE_CONFIG_REPO") or Path(__file__).resolve().parent.parent)
SKILL_DIRS = [REPO / "src" / "skills", REPO / "src" / "dev-core"]
CASES = REPO / "evals" / "triggers.json"
PLUGIN_NAME = "burrow"

# Codex 는 스킬 본문을 셸 명령으로 읽는다. 첫 몇 개 명령 안에 읽지 않으면 이후에도 거의 읽지 않음
CODEX_MAX_COMMANDS = 3
CODEX_TIMEOUT = 240
CODEX_BIN = os.environ.get("CODEX_BIN", "codex")


def load_cases(pattern):
    cases = json.loads(CASES.read_text())["cases"]
    return [c for c in cases if fnmatch.fnmatch(c["id"], pattern)]


def copy_skills(dst):
    dst.mkdir(parents=True, exist_ok=True)
    for d in SKILL_DIRS:
        for child in sorted(d.iterdir()):
            if (child / "SKILL.md").is_file():
                shutil.copytree(child, dst / child.name)


def repo_skills():
    return {c.name for d in SKILL_DIRS for c in d.iterdir() if (c / "SKILL.md").is_file()}


def verdict(case, invoked, scope):
    """(통과 여부, 정답 밖에서 불린 레포 스킬)"""
    invoked = invoked & scope
    hit = any(s in invoked for s in case["expect"]) if case["expect"] else True
    extra = invoked - set(case["expect"]) - set(case.get("ok", []))
    return hit and not extra, extra


# ---------- Claude Code: claude plugin eval 로 위임

def run_claude(cases, runs, model, max_cost):
    with tempfile.TemporaryDirectory(prefix="burrow-eval-") as tmp:
        plugin = Path(tmp) / "plugin"
        copy_skills(plugin / "skills")
        (plugin / ".claude-plugin").mkdir(parents=True)
        (plugin / ".claude-plugin" / "plugin.json").write_text(
            json.dumps({"name": PLUGIN_NAME, "version": "0.0.0", "description": "burrow skills under eval"})
        )
        for c in cases:
            d = plugin / "evals" / c["id"]
            (d / "graders").mkdir(parents=True)
            (d / "prompt.md").write_text(
                "---\nmax_turns: 3\nallowed_tools: [Read, Glob, Grep, Skill]\n---\n\n" + c["prompt"] + "\n"
            )
            # 채점은 trace 의 Skill 입력으로 직접 함. plugin eval 이 grader 를 요구해 호출 횟수만 세는 것을 둠
            (d / "graders" / "any-skill.md").write_text(
                "---\ntype: tool_used\ntool: Skill\nmin: 0\n---\n"
            )
        out = Path(tmp) / "result.json"
        # --keep-temp: grader 는 호출 횟수만 알려 주므로, 어떤 스킬이 불렸는지는 trace 에서 읽음
        cmd = ["claude", "plugin", "eval", str(plugin), "--ablation", "none", "--trust-plugin",
               "--no-publish", "--keep-temp", "--runs", str(runs), "--json", str(out),
               "--max-cost-usd", str(max_cost), "--threshold", "0"]
        if model:
            cmd += ["--model", model]
        subprocess.run(cmd, cwd=plugin, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        if not out.exists():
            sys.exit("claude plugin eval 결과가 없음")
        data = json.loads(out.read_text())

    results = {}
    for c in data["cases"]:
        runs_out = []
        for r in c["arms"]["with"]:
            inv = claude_invoked(r.get("tracePath"))
            # max_turns 초과 같은 실행 에러는 스킬 선택이 끝난 뒤라 채점에 반영하지 않음
            runs_out.append(f"{r['error']}"[:80] if r["error"] and not inv else inv)
        results[c["name"]] = runs_out
    return results, data.get("costUsd")


def claude_invoked(trace_path):
    if not trace_path:
        return set()
    trace = Path(trace_path)
    names = set()
    if trace.is_file():
        for m in re.finditer(r'"name":"Skill","input":\{"skill":"(?:[\w-]+:)?([\w-]+)"', trace.read_text()):
            names.add(m.group(1))
    # 보관된 실행 디렉토리는 권한이 잠겨 있어 풀고 지움
    run_dir = trace.parent.parent
    tmp_roots = {Path("/tmp").resolve(), Path(tempfile.gettempdir()).resolve()}
    if run_dir.name.startswith("e-") and run_dir.parent.resolve() in tmp_roots:
        subprocess.run(["chmod", "-R", "u+rwx", str(run_dir)], check=False)
        shutil.rmtree(run_dir, ignore_errors=True)
    return names


# ---------- Codex: 격리된 HOME 에서 codex exec --json 을 직접 돌린다

SKILL_READ = re.compile(r"\.agents/skills/([\w-]+)/SKILL\.md")


def codex_once(home, work, prompt, model):
    env = dict(os.environ, HOME=str(home), CODEX_HOME=str(home / ".codex"))
    cmd = [CODEX_BIN, "exec", "--json", "--skip-git-repo-check", "-s", "read-only"]
    if model:
        cmd += ["-m", model]
    cmd.append(prompt)
    proc = subprocess.Popen(cmd, cwd=work, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    invoked, commands, started, failure, deadline = [], 0, False, None, time.time() + CODEX_TIMEOUT
    try:
        for line in proc.stdout:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            started = started or e.get("type") == "thread.started"
            item = e.get("item") or {}
            if e.get("type") == "item.started" and item.get("type") == "command_execution":
                commands += 1
                invoked += SKILL_READ.findall(item.get("command", ""))
                if commands >= CODEX_MAX_COMMANDS:
                    break
            if e.get("type") in ("turn.failed", "error"):
                failure = failure or str(e.get("message") or e.get("error") or e["type"])
            if e.get("type") in ("turn.completed", "turn.failed") or time.time() > deadline:
                break
    finally:
        proc.kill()
        _, err = proc.communicate()
    # 세션이 못 떴거나 명령 하나 없이 실패했으면 "호출 안 됨"이 아니라 실행 실패
    if not started or (failure and not commands):
        return None, (failure or (err.strip().splitlines() or ["알 수 없는 에러"])[-1])[:80]
    return set(invoked), None


@contextlib.contextmanager
def shared_auth(src, dst):
    """개인 config·AGENTS.md 없이 인증만 빌려 쓰고, 갱신된 토큰은 원본에 되돌려 씀

    - refresh token 은 1회용이라 사본에서 갱신하고 버리면 원본 로그인이 무효화됨
    """
    shutil.copy2(src, dst)
    before = dst.read_bytes()
    try:
        yield
    finally:
        after = dst.read_bytes() if dst.exists() else before
        if after != before:
            tmp = src.with_name(src.name + ".eval-tmp")
            tmp.write_bytes(after)
            os.chmod(tmp, 0o600)
            os.replace(tmp, src)


def run_codex(cases, runs, model):
    codex_home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    auth = codex_home / "auth.json"
    if not auth.is_file():
        sys.exit(f"Codex 인증 파일 없음: {auth}")
    results = {}
    with tempfile.TemporaryDirectory(prefix="burrow-codex-") as tmp:
        home, work = Path(tmp) / "home", Path(tmp) / "work"
        (home / ".codex").mkdir(parents=True)
        work.mkdir()
        copy_skills(home / ".agents" / "skills")
        for c in cases:
            runs_out = []
            for _ in range(runs):
                with shared_auth(auth, home / ".codex" / "auth.json"):
                    inv, err = codex_once(home, work, c["prompt"], model)
                runs_out.append(err if err else inv)
                if err and "refresh" in err:
                    sys.exit(f"Codex 인증 만료: {err}\n`codex login` 으로 다시 로그인한 뒤 실행")
            results[c["id"]] = runs_out
    return results


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--agent", choices=["claude", "codex", "all"], default="all")
    p.add_argument("--case", default="*", help="케이스 id glob")
    p.add_argument("--runs", type=int, default=1)
    p.add_argument("--claude-model")
    p.add_argument("--codex-model")
    p.add_argument("--max-cost-usd", type=float, default=5.0, help="Claude 쪽 비용 상한")
    a = p.parse_args()

    cases = load_cases(a.case)
    if not cases:
        sys.exit("일치하는 케이스 없음")

    table = {}
    if a.agent in ("claude", "all"):
        if not shutil.which("claude"):
            sys.exit("claude CLI 없음")
        table["claude"], cost = run_claude(cases, a.runs, a.claude_model, a.max_cost_usd)
        print(f"claude 비용: ${cost:.3f}" if cost is not None else "claude 비용: 알 수 없음")
    if a.agent in ("codex", "all"):
        if subprocess.run([CODEX_BIN, "--version"], capture_output=True).returncode != 0:
            sys.exit(f"{CODEX_BIN} 실행 실패. 다른 설치본은 CODEX_BIN=<경로> 로 지정")
        table["codex"] = run_codex(cases, a.runs, a.codex_model)
    sys.exit(report(cases, table, repo_skills()))


def report(cases, table, scope):
    """케이스 표, 스킬별 precision·recall, 오답 목록을 출력하고 exit code 반환"""
    failed = False
    agents = list(table)
    print("\n%-36s %s" % ("case", "  ".join("%-8s" % x for x in agents)))
    # stats[agent][skill] = [불려야 한 회차, 그중 불린 회차, 불린 회차, 그중 정답·ok 인 회차]
    stats = {ag: {} for ag in agents}
    misses = []
    for c in cases:
        cells = []
        for ag in agents:
            runs = table[ag].get(c["id"], [])
            passed = errs = 0
            for inv in runs:
                if isinstance(inv, str):
                    errs += 1
                    misses.append(f"{ag:6} {c['id']}: 실행 실패 {inv}")
                    continue
                ok, extra = verdict(c, inv, scope)
                passed += ok
                # expect 가 여럿인 케이스는 어느 하나만 불려도 정답이라 스킬별 recall 에서 뺌
                if len(c["expect"]) == 1:
                    s = c["expect"][0]
                    st = stats[ag].setdefault(s, [0, 0, 0, 0])
                    st[0] += 1
                    st[1] += s in inv
                for s in inv & scope:
                    st = stats[ag].setdefault(s, [0, 0, 0, 0])
                    st[2] += 1
                    st[3] += s not in extra
                if not ok:
                    got = ",".join(sorted(inv & scope)) or "없음"
                    misses.append(f"{ag:6} {c['id']}: 기대 {','.join(c['expect']) or '없음'} / 호출 {got}")
            cells.append("%-8s" % (f"{passed}/{len(runs)}" + (f" E{errs}" if errs else "")))
            failed = failed or not runs or passed < len(runs)
        print("%-36s %s" % (c["id"], "  ".join(cells)))

    for ag in agents:
        print(f"\n[{ag}] 스킬별  recall(불려야 할 때 불림)  precision(불렸을 때 맞음)")
        for s, (pos, hit, called, right) in sorted(stats[ag].items()):
            rec = f"{hit}/{pos}" if pos else "-"
            prec = f"{right}/{called}" if called else "-"
            print(f"  {s:20} {rec:>8} {prec:>8}")
    if misses:
        print("\n오답")
        for m in misses:
            print("  " + m)
    return 1 if failed else 0

if __name__ == "__main__":
    main()
