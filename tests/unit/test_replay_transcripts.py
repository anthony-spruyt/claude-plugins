#!/usr/bin/env python3
"""Unit tests for the transcript replay tool."""

import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests", "helpers"))

import replay_transcripts as rt

BLOCK_RULE = """---
name: block-test-dump
enabled: true
event: bash
pattern: dumpall
action: block
---
blocked
"""

WARN_RULE = """---
name: warn-test-cat
enabled: true
event: bash
pattern: ^cat\\b
action: warn
---
warned
"""

FILE_RULE = """---
name: warn-test-todo
enabled: true
event: file
conditions:
  - field: new_text
    operator: contains
    pattern: TODO
action: warn
---
todo
"""


def tool_use(tool_id, name, tool_input, cwd="/work"):
    return {
        "type": "assistant", "cwd": cwd, "sessionId": "s1",
        "message": {"content": [
            {"type": "text", "text": "hi"},
            {"type": "tool_use", "id": tool_id, "name": name, "input": tool_input},
        ]},
    }


def tool_result(tool_id, content):
    return {
        "type": "user", "cwd": "/work",
        "message": {"content": [{"type": "tool_result", "tool_use_id": tool_id, "content": content}]},
    }


def post_hook(tool_id, rule_name):
    return {
        "type": "attachment",
        "attachment": {
            "type": "hook_blocking_error", "toolUseID": tool_id, "hookEvent": "PostToolUse",
            "blockingError": {"blockingError": f"[python3 posttooluse.py]: **[{rule_name}]**\nmsg"},
        },
    }


def write_jsonl(path, entries):
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    return str(path)


def write_rules(tmp_path, *rules):
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    for i, body in enumerate(rules):
        (rules_dir / f"rule{i}.md").write_text(body)
    return rt.load_rule_dir(str(rules_dir))


class TestParseTranscript:
    def test_extracts_tool_calls_with_cwd(self, tmp_path):
        path = write_jsonl(tmp_path / "t.jsonl", [tool_use("t1", "Bash", {"command": "ls"}, cwd="/repo")])
        calls, _ = rt.parse_transcript(path)
        assert calls == [{"id": "t1", "tool": "Bash", "input": {"command": "ls"}, "cwd": "/repo", "source": path}]

    def test_pretooluse_block_in_tool_result_is_recorded_as_fired(self, tmp_path):
        path = write_jsonl(tmp_path / "t.jsonl", [
            tool_use("t1", "Bash", {"command": "env"}),
            tool_result("t1", "PreToolUse:Bash hook error: [x]: **[block-env-dump]**\nBlocked"),
        ])
        _, fired = rt.parse_transcript(path)
        assert fired == {"t1": {"block-env-dump"}}

    def test_tool_result_content_list_is_searched(self, tmp_path):
        path = write_jsonl(tmp_path / "t.jsonl", [
            tool_use("t1", "Bash", {"command": "env"}),
            tool_result("t1", [{"type": "text", "text": "PreToolUse:Bash hook error: **[block-env-dump]**"}]),
        ])
        _, fired = rt.parse_transcript(path)
        assert fired == {"t1": {"block-env-dump"}}

    def test_posttooluse_attachment_is_recorded_as_fired(self, tmp_path):
        path = write_jsonl(tmp_path / "t.jsonl", [
            tool_use("t1", "Bash", {"command": "cat x"}),
            post_hook("t1", "warn-use-read-tool"),
        ])
        _, fired = rt.parse_transcript(path)
        assert fired == {"t1": {"warn-use-read-tool"}}

    def test_rule_names_quoted_in_ordinary_output_are_not_fires(self, tmp_path):
        path = write_jsonl(tmp_path / "t.jsonl", [
            tool_use("t1", "Bash", {"command": "grep -r block- ."}),
            tool_result("t1", "rules.md: **[block-env-dump]** example"),
        ])
        _, fired = rt.parse_transcript(path)
        assert fired == {}

    def test_skips_malformed_lines(self, tmp_path):
        path = tmp_path / "t.jsonl"
        path.write_text("not json\n" + json.dumps(tool_use("t1", "Read", {"file_path": "/a"})) + "\n")
        calls, _ = rt.parse_transcript(str(path))
        assert [c["id"] for c in calls] == ["t1"]


class TestRepoRules:
    def test_loads_every_plugin_and_project_rule_folder(self):
        dirs = [os.path.relpath(d, REPO_ROOT) for d in rt.repo_rule_dirs()]
        assert {"security-hooks/hookify-plus", "best-practices/hookify-plus", ".claude/hookify-plus"} <= set(dirs)

    def test_skips_the_engine_folder_with_no_rules(self):
        assert "hookify-plus/hookify-plus" not in [os.path.relpath(d, REPO_ROOT) for d in rt.repo_rule_dirs()]


class TestReplay:
    def test_reports_each_matching_rule_by_name(self, tmp_path):
        rules = write_rules(tmp_path, BLOCK_RULE, WARN_RULE)
        call = {"id": "t1", "tool": "Bash", "input": {"command": "cat dumpall"}, "cwd": str(tmp_path)}
        assert rt.matching_rules(call, rules) == {"block-test-dump", "warn-test-cat"}

    def test_rules_only_apply_to_their_tool_event(self, tmp_path):
        rules = write_rules(tmp_path, WARN_RULE, FILE_RULE)
        call = {"id": "t1", "tool": "Edit", "input": {"file_path": "/a", "old_string": "", "new_string": "TODO cat"},
                "cwd": str(tmp_path)}
        assert rt.matching_rules(call, rules) == {"warn-test-todo"}

    def test_unknown_tools_match_nothing(self, tmp_path):
        rules = write_rules(tmp_path, BLOCK_RULE)
        call = {"id": "t1", "tool": "WebFetch", "input": {"url": "dumpall"}, "cwd": str(tmp_path)}
        assert rt.matching_rules(call, rules) == set()


class TestSuspects:
    def test_secret_looking_bash_with_no_block_is_a_suspect(self):
        assert rt.is_suspect({"tool": "Bash", "input": {"command": "cat ~/.aws/credentials"}}, set())

    def test_secret_looking_call_already_blocked_is_not_a_suspect(self):
        call = {"tool": "Bash", "input": {"command": "cat ~/.aws/credentials"}}
        assert not rt.is_suspect(call, {"block-read-cloud-creds"})

    def test_plain_command_is_not_a_suspect(self):
        assert not rt.is_suspect({"tool": "Bash", "input": {"command": "git status"}}, set())

    def test_read_of_secret_path_is_a_suspect(self):
        assert rt.is_suspect({"tool": "Read", "input": {"file_path": "/repo/secrets.enc.yaml"}}, set())

    def test_env_inside_a_file_name_is_not_a_suspect(self):
        call = {"tool": "Bash", "input": {"command": "ls -l rules/block-env-dump.md env.py"}}
        assert not rt.is_suspect(call, set())

    def test_bare_env_command_is_a_suspect(self):
        assert rt.is_suspect({"tool": "Bash", "input": {"command": "cd x && env | sort"}}, set())


class TestBuildReport:
    def run_report(self, tmp_path, entries, *rules):
        path = write_jsonl(tmp_path / "t.jsonl", entries)
        return rt.build_report([path], write_rules(tmp_path, *rules))

    def test_counts_matches_per_rule_and_dedupes_identical_calls(self, tmp_path):
        report = self.run_report(tmp_path, [
            tool_use("t1", "Bash", {"command": "cat a"}),
            tool_use("t2", "Bash", {"command": "cat a"}),
            tool_use("t3", "Bash", {"command": "cat b"}),
        ], WARN_RULE)
        rule = report["rules"]["warn-test-cat"]
        assert rule["hits"] == 3
        assert [e["command"] for e in rule["examples"]] == ["cat a", "cat b"]
        assert rule["examples"][0]["count"] == 2

    def test_rules_that_never_match_are_listed_with_zero_hits(self, tmp_path):
        report = self.run_report(tmp_path, [tool_use("t1", "Bash", {"command": "ls"})], BLOCK_RULE)
        assert report["rules"]["block-test-dump"]["hits"] == 0

    def test_fired_in_log_but_not_now_is_reported_as_stopped(self, tmp_path):
        report = self.run_report(tmp_path, [
            tool_use("t1", "Bash", {"command": "ls"}),
            post_hook("t1", "warn-test-cat"),
        ], WARN_RULE)
        assert [e["command"] for e in report["rules"]["warn-test-cat"]["stopped"]] == ["ls"]

    def test_matches_now_but_not_in_log_is_reported_as_started(self, tmp_path):
        report = self.run_report(tmp_path, [tool_use("t1", "Bash", {"command": "cat a"})], WARN_RULE)
        assert [e["command"] for e in report["rules"]["warn-test-cat"]["started"]] == ["cat a"]

    def test_rules_not_loaded_are_ignored_in_drift(self, tmp_path):
        report = self.run_report(tmp_path, [
            tool_use("t1", "Bash", {"command": "ls"}),
            post_hook("t1", "warn-other-project"),
        ], WARN_RULE)
        assert "warn-other-project" not in report["rules"]

    def test_examples_mask_secrets_in_commands(self, tmp_path):
        report = self.run_report(tmp_path, [
            tool_use("t1", "Bash", {"command": "cat a; echo ghp_abcdefghijklmnopqrstuvwxyz0123456789"}),
        ], WARN_RULE)
        shown = report["rules"]["warn-test-cat"]["examples"][0]["command"]
        assert "ghp_abcdefghijklmnopqrstuvwxyz0123456789" not in shown

    def test_suspects_are_collected(self, tmp_path):
        report = self.run_report(tmp_path, [tool_use("t1", "Bash", {"command": "cat ~/.ssh/id_rsa"})], BLOCK_RULE)
        assert [s["command"] for s in report["suspects"]] == ["cat ~/.ssh/id_rsa"]

    def test_long_commands_are_truncated(self, tmp_path):
        report = self.run_report(tmp_path, [tool_use("t1", "Bash", {"command": "cat " + "x" * 5000})], WARN_RULE)
        assert len(report["rules"]["warn-test-cat"]["examples"][0]["command"]) <= rt.MAX_SHOWN + 20


class TestRedact:
    def test_redacts_known_token_shapes(self):
        shown = rt.redact("curl -H 'Authorization: Bearer ghp_abcdefghijklmnopqrstuvwxyz0123456789' x")
        assert "ghp_abcdefghijklmnopqrstuvwxyz0123456789" not in shown

    def test_redacts_secret_named_assignments(self):
        shown = rt.redact("export API_TOKEN=abc123secretvalue; DB_PASSWORD='hunter2hunter2' ls")
        assert "abc123secretvalue" not in shown
        assert "hunter2hunter2" not in shown
        assert "API_TOKEN=" in shown

    def test_redacts_private_key_blocks(self):
        shown = rt.redact("-----BEGIN OPENSSH PRIVATE KEY-----\nAAAAB3Nza\n-----END OPENSSH PRIVATE KEY-----")
        assert "AAAAB3Nza" not in shown

    def test_leaves_variable_references_alone(self):
        assert rt.redact('echo "$API_TOKEN" TOKEN=$X') == 'echo "$API_TOKEN" TOKEN=$X'


class TestFindTranscripts:
    def test_finds_session_and_subagent_logs(self, tmp_path):
        (tmp_path / "proj" / "sess" / "subagents").mkdir(parents=True)
        (tmp_path / "proj" / "a.jsonl").write_text("")
        (tmp_path / "proj" / "sess" / "subagents" / "agent-1.jsonl").write_text("")
        found = rt.find_transcripts(str(tmp_path))
        assert sorted(os.path.basename(f) for f in found) == ["a.jsonl", "agent-1.jsonl"]

    def make_projects(self, tmp_path):
        for project in ("-workspaces-claude-plugins", "-workspaces-spruyt-labs", "-workspaces-xfg"):
            (tmp_path / project).mkdir()
            (tmp_path / project / "s.jsonl").write_text("")
        return str(tmp_path)

    def projects_of(self, found):
        return sorted(os.path.basename(os.path.dirname(f)) for f in found)

    def test_include_keeps_only_matching_projects(self, tmp_path):
        found = rt.find_transcripts(self.make_projects(tmp_path), include=["spruyt-labs", "xfg"])
        assert self.projects_of(found) == ["-workspaces-spruyt-labs", "-workspaces-xfg"]

    def test_exclude_drops_matching_projects(self, tmp_path):
        found = rt.find_transcripts(self.make_projects(tmp_path), exclude=["claude-plugins"])
        assert self.projects_of(found) == ["-workspaces-spruyt-labs", "-workspaces-xfg"]
