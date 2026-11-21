"""burrow 훅을 실제 진입점(hook.py)에 stdin 을 넣어 검증한다."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "src" / "hooks" / "burrow" / "hook.py"
sys.dont_write_bytecode = True
sys.path.insert(0, str(HOOK.parent))

from commands import COMMIT, PR_BODY, PR_CREATE, classify  # noqa: E402


class ClassifyTest(unittest.TestCase):
    def test_commit_forms(self):
        for cmd in ["git commit -m x", "git -C /a/b commit", "cd x && git add . && git commit -F -",
                    "FOO=1 git -c user.name=a commit --amend"]:
            self.assertEqual(classify(cmd), {COMMIT}, cmd)

    def test_words_inside_quotes_or_heredoc_are_not_commands(self):
        self.assertEqual(classify("echo 'git commit'"), set())
        self.assertEqual(classify("git log --grep \"gh pr create\""), set())
        self.assertEqual(classify("cat <<'EOF' > f\ngit commit -m x\nEOF\nls"), set())

    def test_pr_forms(self):
        self.assertEqual(classify("gh pr create --title t --body b"), {PR_CREATE})
        self.assertEqual(classify("gh stack submit"), {PR_CREATE})
        self.assertEqual(classify("gh pr edit 12 --body-file b.md"), {PR_BODY})
        self.assertEqual(classify("gh pr edit 12 --add-reviewer x"), set())
        self.assertEqual(classify("gh pr view 12"), set())


class HookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = {**os.environ, "BURROW_STATE_DIR": self.tmp.name}
        self.env.pop("BURROW_GATES", None)
        self.src = Path(self.tmp.name) / "repo" / "src"
        self.src.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def run_hook(self, payload, **env):
        payload = {"session_id": "s1", **payload}
        r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), text=True,
                           capture_output=True, env={**self.env, **env}, check=True)
        return json.loads(r.stdout) if r.stdout.strip() else None

    def bash(self, command, **env):
        return self.run_hook({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                              "tool_input": {"command": command}}, **env)

    def skill(self, name):
        self.run_hook({"hook_event_name": "PostToolUse", "tool_name": "Skill", "tool_input": {"skill": name}})

    def edit(self, name="a.ts", lines=1):
        path = self.src / name
        path.write_text("x\n" * lines)
        return self.run_hook({"hook_event_name": "PostToolUse", "tool_name": "Edit",
                              "tool_input": {"file_path": str(path), "new_string": "x"}})

    def stop(self, active=False):
        return self.run_hook({"hook_event_name": "Stop", "stop_hook_active": active})

    def denied(self, out):
        return out and out["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_commit_blocked_until_readability_pass_after_last_edit(self):
        self.edit()
        out = self.bash("git commit -m x")
        self.assertTrue(self.denied(out))
        self.assertIn('Skill(skill: "readability-pass")', out["hookSpecificOutput"]["permissionDecisionReason"])
        self.skill("readability-pass")
        self.assertIsNone(self.bash("git commit -m x"))
        self.edit()
        self.assertTrue(self.denied(self.bash("git commit -m x")))

    def test_pr_create_needs_all_and_reviewer_after_edit(self):
        self.edit()
        for s in ["readability-pass", "pr-slicing", "pr-writing"]:
            self.skill(s)
        reason = self.bash("gh pr create")["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("burrow-reviewer", reason)
        self.assertNotIn("pr-slicing", reason)
        self.run_hook({"hook_event_name": "SubagentStop", "agent_type": "burrow-reviewer"})
        self.assertIsNone(self.bash("gh pr create"))

    def test_gates_off_by_user_env(self):
        self.edit()
        self.assertIsNone(self.bash("git commit -m x", BURROW_GATES="off"))

    def test_slash_command_counts_as_skill(self):
        self.edit()
        self.run_hook({"hook_event_name": "UserPromptSubmit", "prompt": "/readability-pass 해줘"})
        self.assertIsNone(self.bash("git commit -m x"))

    def test_stop_blocks_once_per_edit_and_never_when_active(self):
        self.assertIsNone(self.stop())
        self.edit()
        self.assertIsNone(self.stop(active=True))
        self.assertEqual(self.stop()["decision"], "block")
        self.assertIsNone(self.stop())
        self.edit()
        self.assertEqual(self.stop()["decision"], "block")

    def test_stop_skipped_while_subagent_runs(self):
        self.edit()
        self.run_hook({"hook_event_name": "SubagentStart", "agent_id": "a1", "agent_type": "general-purpose"})
        self.assertIsNone(self.stop())
        self.run_hook({"hook_event_name": "SubagentStop", "agent_id": "a1", "agent_type": "general-purpose"})
        self.assertEqual(self.stop()["decision"], "block")

    def test_subagent_stop_without_id_closes_same_type(self):
        self.edit()
        self.run_hook({"hook_event_name": "SubagentStart", "agent_id": "a1", "agent_type": "burrow-reviewer"})
        self.run_hook({"hook_event_name": "SubagentStop", "agent_type": "burrow-reviewer"})
        self.assertEqual(self.stop()["decision"], "block")

    def transcript(self, *blocks):
        path = Path(self.tmp.name) / "t.jsonl"
        rows = [{"type": "user", "message": {"content": "x"}},
                {"type": "assistant", "isSidechain": True, "message": {"content": [{"type": "text", "text": "a?"}]}},
                {"type": "assistant", "message": {"content": list(blocks)}}]
        path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows))
        return str(path)

    def test_stop_skipped_when_turn_ends_with_question(self):
        self.edit()
        asked = self.transcript({"type": "text", "text": "어느 쪽으로 할까요?"})
        self.assertIsNone(self.run_hook({"hook_event_name": "Stop", "transcript_path": asked}))
        tool = self.transcript({"type": "tool_use", "name": "AskUserQuestion", "input": {}})
        self.assertIsNone(self.run_hook({"hook_event_name": "Stop", "transcript_path": tool}))
        report = self.transcript({"type": "text", "text": "반영했습니다."})
        self.assertEqual(self.run_hook({"hook_event_name": "Stop", "transcript_path": report})["decision"], "block")

    def test_unreadable_transcript_still_blocks(self):
        self.edit()
        out = self.run_hook({"hook_event_name": "Stop", "transcript_path": "/nonexistent/t.jsonl"})
        self.assertEqual(out["decision"], "block")

    def test_scratch_edits_do_not_count(self):
        self.run_hook({"hook_event_name": "PostToolUse", "tool_name": "Write",
                       "tool_input": {"file_path": "/private/tmp/x/scratchpad/a.py", "content": ""}})
        self.assertIsNone(self.stop())

    def test_new_file_nudge_once_and_skips_loaded_skills(self):
        self.skill("abstraction")
        pre = {"hook_event_name": "PreToolUse", "tool_name": "Write",
               "tool_input": {"file_path": str(self.src / "new.ts"), "content": "import { Effect } from 'effect'"}}
        text = self.run_hook(pre)["hookSpecificOutput"]["additionalContext"]
        for s in ["file-map", "module-boundaries", "typescript", "effect"]:
            self.assertIn(f'"{s}"', text)
        self.assertNotIn('"abstraction"', text)
        pre["tool_input"]["file_path"] = str(self.src / "other.ts")
        self.assertIsNone(self.run_hook(pre))

    def test_contract_and_test_nudges(self):
        out = self.run_hook({"hook_event_name": "PreToolUse", "tool_name": "Edit",
                             "tool_input": {"file_path": str(self.src / "index.ts"), "new_string": ""}})
        self.assertIn('"type-modeling"', out["hookSpecificOutput"]["additionalContext"])
        out = self.run_hook({"hook_event_name": "PreToolUse", "tool_name": "Edit",
                             "tool_input": {"file_path": str(self.src / "a.test.ts"), "new_string": ""}})
        self.assertIn('"write-test-code"', out["hookSpecificOutput"]["additionalContext"])

    def test_cohesion_nudge_when_file_crosses_limit_once(self):
        self.assertIsNone(self.edit(lines=150))
        self.assertIn('"cohesion"', self.edit(lines=201)["hookSpecificOutput"]["additionalContext"])
        self.assertIsNone(self.edit(lines=230))

    def test_asset_links_blocked_outside_allowlist(self):
        cfg = Path(self.tmp.name) / "cfg" / "pr-assets"
        cfg.mkdir(parents=True)
        (cfg / "config.json").write_text(json.dumps(
            {"remote": "git@alias:me/assets.git", "allow": ["me/*"]}))
        env = {"XDG_CONFIG_HOME": str(cfg.parent), "BURROW_GATES": "off"}
        url = "https://github.com/me/assets/blob/abc/assets/x.svg?raw=true"
        body = Path(self.tmp.name) / "body.md"
        body.write_text(f"![x]({url})")
        self.assertTrue(self.denied(self.bash(f'gh pr create -R corp/app --body "![x]({url})"', **env)))
        self.assertTrue(self.denied(self.bash(f"gh pr edit 1 --repo corp/app --body-file {body}", **env)))
        self.assertIsNone(self.bash(f'gh pr create -R me/tool --body "![x]({url})"', **env))
        self.assertIsNone(self.bash('gh pr create -R corp/app --body "plain"', **env))
        self.assertIsNone(self.bash(f'echo "{url}"', **env))

    def test_broken_input_passes(self):
        r = subprocess.run([sys.executable, str(HOOK)], input="not json", text=True, capture_output=True,
                           env=self.env)
        self.assertEqual((r.returncode, r.stdout), (0, ""))


if __name__ == "__main__":
    unittest.main()
