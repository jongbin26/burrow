#!/usr/bin/env python3
"""스킬 자동 호출 eval. evals/triggers.json 의 케이스를 Claude Code·Codex 에 돌려 호출된 스킬을 채점한다.

사용:
  bin/eval-triggers.py                       # 두 에이전트, 케이스당 1회
  bin/eval-triggers.py --agent claude --runs 3 --case 'root-cause-*'
  bin/eval-triggers.py --agent codex --codex-model gpt-5.5
  CODEX_BIN=/opt/homebrew/bin/codex bin/eval-triggers.py --agent codex

모든 실행은 실제 모델 호출이라 비용이 든다. 실패 케이스가 하나라도 있으면 exit 1.
"""
import argparse
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


def verdict(case, invoked):
    hit = not case["expect"] or any(s in invoked for s in case["expect"])
    leaked = [s for s in case.get("forbid", []) if s in invoked]
    return hit and not leaked


# ---------- Claude Code: claude plugin eval 로 위임

def skill_regex(names):
    alt = "|".join(re.escape(n) for n in names)
    return r'"skill"\s*:\s*"(?:[\w-]+:)?(?:%s)"' % alt


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
            # expect 와 forbid 는 grader 대신 trace 의 Skill 입력으로 직접 채점. grader 는 리포트용
            if c["expect"]:
                (d / "graders" / "expect.md").write_text(
                    "---\ntype: tool_used\ntool: Skill\ninput_match: '%s'\n---\n" % skill_regex(c["expect"])
                )
            if c.get("forbid"):
                (d / "graders" / "forbid.md").write_text(
                    "---\ntype: tool_used\ntool: Skill\ninput_match: '%s'\nmin: 0\nmax: 0\n---\n"
                    % skill_regex(c["forbid"])
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

    by_id = {c["id"]: c for c in cases}
    results, invoked_log = {}, {}
    for c in data["cases"]:
        rows, seen = [], []
        for r in c["arms"]["with"]:
            inv = claude_invoked(r.get("tracePath"))
            # max_turns 초과 같은 실행 에러는 스킬 선택이 끝난 뒤라 채점에 반영하지 않음
            if r["error"] and not inv:
                rows.append(None)
                seen.append([f"ERR {r['error']}"[:80]])
            else:
                rows.append(verdict(by_id[c["name"]], inv))
                seen.append(sorted(inv))
        results[c["name"]], invoked_log[c["name"]] = rows, seen
    return results, invoked_log, data.get("costUsd")


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
    invoked, commands, started, deadline = [], 0, False, time.time() + CODEX_TIMEOUT
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
            if e.get("type") in ("turn.completed", "turn.failed", "error") or time.time() > deadline:
                break
    finally:
        proc.kill()
        _, err = proc.communicate()
    # 세션이 시작되지 않았으면 "호출 안 됨"이 아니라 실행 실패
    if not started:
        return None, (err.strip().splitlines() or ["알 수 없는 에러"])[-1][:80]
    return set(invoked), None


def run_codex(cases, runs, model):
    codex_home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    auth = codex_home / "auth.json"
    if not auth.is_file():
        sys.exit(f"Codex 인증 파일 없음: {auth}")
    results, invoked_log = {}, {}
    with tempfile.TemporaryDirectory(prefix="burrow-codex-") as tmp:
        home, work = Path(tmp) / "home", Path(tmp) / "work"
        (home / ".codex").mkdir(parents=True)
        work.mkdir()
        # 개인 config·AGENTS.md 는 가져오지 않고 인증만 복사. 임시 디렉토리와 함께 삭제
        shutil.copy2(auth, home / ".codex" / "auth.json")
        copy_skills(home / ".agents" / "skills")
        for c in cases:
            rows, seen = [], []
            for _ in range(runs):
                inv, err = codex_once(home, work, c["prompt"], model)
                rows.append(None if err else verdict(c, inv))
                seen.append([f"ERR {err}"] if err else sorted(inv))
            results[c["id"]], invoked_log[c["id"]] = rows, seen
    return results, invoked_log


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

    table, seen, failed = {}, {}, False
    if a.agent in ("claude", "all"):
        if not shutil.which("claude"):
            sys.exit("claude CLI 없음")
        table["claude"], seen["claude"], cost = run_claude(cases, a.runs, a.claude_model, a.max_cost_usd)
        print(f"claude 비용: ${cost:.3f}" if cost is not None else "claude 비용: 알 수 없음")
    if a.agent in ("codex", "all"):
        if subprocess.run([CODEX_BIN, "--version"], capture_output=True).returncode != 0:
            sys.exit(f"{CODEX_BIN} 실행 실패. 다른 설치본은 CODEX_BIN=<경로> 로 지정")
        table["codex"], seen["codex"] = run_codex(cases, a.runs, a.codex_model)

    agents = list(table)
    print("\n%-36s %s" % ("case", "  ".join("%-8s" % x for x in agents)))
    for c in cases:
        cells = []
        for ag in agents:
            rows = table[ag].get(c["id"], [])
            n, errs = sum(1 for r in rows if r), sum(1 for r in rows if r is None)
            cells.append("%-8s" % (f"{n}/{len(rows)}" + (f" E{errs}" if errs else "")))
            if not rows or n < len(rows):
                failed = True
        print("%-36s %s" % (c["id"], "  ".join(cells)))
        for ag in agents:
            runs_seen = seen[ag].get(c["id"], [])
            print("%-36s   %s 호출: %s" % ("", ag, " | ".join(",".join(r) or "-" for r in runs_seen)))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
