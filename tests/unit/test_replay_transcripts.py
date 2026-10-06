#!/usr/bin/env python3
"""Unit tests for the transcript replay tool."""

import json
import os
import sys
import time
from typing import ClassVar

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests", "helpers"))

import replay_transcripts as rt

# Built at runtime so secret scanners do not flag the fakes
FAKE = "hunter2" + "pass"
FAKE_GH = "ghp_" + "Q" * 36

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
        "type": "assistant",
        "cwd": cwd,
        "sessionId": "s1",
        "message": {
            "content": [
                {"type": "text", "text": "hi"},
                {"type": "tool_use", "id": tool_id, "name": name, "input": tool_input},
            ]
        },
    }


def tool_result(tool_id, content):
    return {
        "type": "user",
        "cwd": "/work",
        "message": {"content": [{"type": "tool_result", "tool_use_id": tool_id, "content": content}]},
    }


def post_hook(tool_id, rule_name):
    return {
        "type": "attachment",
        "attachment": {
            "type": "hook_blocking_error",
            "toolUseID": tool_id,
            "hookEvent": "PostToolUse",
            "blockingError": {"blockingError": f"[python3 posttooluse.py]: **[{rule_name}]**\nmsg"},
        },
    }


EMPTY_REPORT = {
    "generated": "now",
    "transcripts": 0,
    "calls": 0,
    "rules": {},
    "suspects": [],
    "suspects_total": 0,
    "timeouts": [],
}


def timeout_entry(tool_id, command="python3 ${CLAUDE_PLUGIN_ROOT}/hooks/pretooluse.py"):
    return {
        "type": "attachment",
        "attachment": {
            "type": "hook_cancelled",
            "toolUseID": tool_id,
            "command": command,
            "hookEvent": "PreToolUse",
            "timedOut": True,
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
        assert calls == [
            {
                "id": "t1",
                "tool": "Bash",
                "input": {"command": "ls"},
                "cwd": "/repo",
                "source": path,
                "blocked": False,
                "timed_out": False,
            }
        ]

    def test_every_rule_in_a_multi_rule_block_is_recorded(self, tmp_path):
        path = write_jsonl(
            tmp_path / "t.jsonl",
            [
                tool_use("t1", "Bash", {"command": "env"}),
                tool_result("t1", "PreToolUse:Bash hook error: [x]: **[block-a]**\nmsg\n\n**[block-b]**\nmsg"),
            ],
        )
        _, fired = rt.parse_transcript(path)
        assert fired == {"t1": {"block-a", "block-b"}}

    def test_hook_message_quoted_inside_output_is_not_a_fire(self, tmp_path):
        path = write_jsonl(
            tmp_path / "t.jsonl",
            [
                tool_use("t1", "Bash", {"command": "grep -r hook logs"}),
                tool_result("t1", "logs/a: PreToolUse:Bash hook error: **[block-a]**"),
            ],
        )
        _, fired = rt.parse_transcript(path)
        assert fired == {}

    def test_pretooluse_timeout_marks_the_call(self, tmp_path):
        path = write_jsonl(
            tmp_path / "t.jsonl",
            [
                tool_use("t1", "Bash", {"command": "x"}),
                timeout_entry("t1"),
            ],
        )
        calls, _ = rt.parse_transcript(path)
        assert calls[0]["timed_out"] is True

    def test_timeout_of_another_hook_script_is_ignored(self, tmp_path):
        path = write_jsonl(
            tmp_path / "t.jsonl",
            [
                tool_use("t1", "Bash", {"command": "x"}),
                timeout_entry("t1", command="node other-plugin/check.js"),
            ],
        )
        calls, _ = rt.parse_transcript(path)
        assert calls[0]["timed_out"] is False

    def test_unhashable_ids_do_not_crash(self, tmp_path):
        path = write_jsonl(
            tmp_path / "t.jsonl",
            [
                tool_use(["t1"], "Bash", {"command": "x"}),
                tool_result(["t1"], "PreToolUse:Bash hook error: **[block-x]**"),
                timeout_entry(["t1"]),
            ],
        )
        calls, fired = rt.parse_transcript(path)
        assert fired == {}
        assert [c["blocked"] for c in calls] == [False]

    def test_malformed_entries_do_not_crash(self, tmp_path):
        path = write_jsonl(
            tmp_path / "t.jsonl",
            [
                {"type": "attachment", "attachment": {"type": None, "toolUseID": "t9"}},
                {"type": "attachment", "attachment": "text"},
                {"type": "assistant", "message": "text"},
                {"type": "user", "message": {"content": [{"type": "tool_result", "content": None}]}},
                tool_use("t1", "Bash", "not a dict"),
            ],
        )
        calls, fired = rt.parse_transcript(path)
        assert [(c["id"], c["input"]) for c in calls] == [("t1", {})]
        assert fired == {}

    def test_pretooluse_block_in_tool_result_is_recorded_as_fired(self, tmp_path):
        path = write_jsonl(
            tmp_path / "t.jsonl",
            [
                tool_use("t1", "Bash", {"command": "env"}),
                tool_result("t1", "PreToolUse:Bash hook error: [x]: **[block-env-dump]**\nBlocked"),
            ],
        )
        _, fired = rt.parse_transcript(path)
        assert fired == {"t1": {"block-env-dump"}}

    def test_tool_result_content_list_is_searched(self, tmp_path):
        path = write_jsonl(
            tmp_path / "t.jsonl",
            [
                tool_use("t1", "Bash", {"command": "env"}),
                tool_result("t1", [{"type": "text", "text": "PreToolUse:Bash hook error: **[block-env-dump]**"}]),
            ],
        )
        _, fired = rt.parse_transcript(path)
        assert fired == {"t1": {"block-env-dump"}}

    def test_posttooluse_attachment_is_recorded_as_fired(self, tmp_path):
        path = write_jsonl(
            tmp_path / "t.jsonl",
            [
                tool_use("t1", "Bash", {"command": "cat x"}),
                post_hook("t1", "warn-use-read-tool"),
            ],
        )
        _, fired = rt.parse_transcript(path)
        assert fired == {"t1": {"warn-use-read-tool"}}

    def test_rule_names_quoted_in_ordinary_output_are_not_fires(self, tmp_path):
        path = write_jsonl(
            tmp_path / "t.jsonl",
            [
                tool_use("t1", "Bash", {"command": "grep -r block- ."}),
                tool_result("t1", "rules.md: **[block-env-dump]** example"),
            ],
        )
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

    def test_extra_rule_folders_add_to_the_repo_ones(self, tmp_path):
        dirs = rt.resolve_rule_dirs([str(tmp_path)])
        assert dirs[-1] == str(tmp_path)
        assert set(rt.repo_rule_dirs()) <= set(dirs)


class TestReplay:
    def test_reports_each_matching_rule_by_name(self, tmp_path):
        rules = write_rules(tmp_path, BLOCK_RULE, WARN_RULE)
        call = {"id": "t1", "tool": "Bash", "input": {"command": "cat dumpall"}, "cwd": str(tmp_path)}
        assert rt.matching_rules(call, rules) == {"block-test-dump", "warn-test-cat"}

    def test_rules_only_apply_to_their_tool_event(self, tmp_path):
        rules = write_rules(tmp_path, WARN_RULE, FILE_RULE)
        call = {
            "id": "t1",
            "tool": "Edit",
            "input": {"file_path": "/a", "old_string": "", "new_string": "TODO cat"},
            "cwd": str(tmp_path),
        }
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

    def test_any_matched_block_rule_clears_a_suspect_whatever_its_name(self):
        assert not rt.is_suspect({"tool": "Bash", "input": {"command": "cat ~/.aws/credentials"}}, {"no-secrets"})

    def test_grep_path_into_a_secret_folder_is_a_suspect(self):
        assert rt.is_suspect({"tool": "Grep", "input": {"pattern": "x", "path": "/home/u/.ssh"}}, set())

    def test_set_dump_before_a_newline_is_a_suspect(self):
        assert rt.is_suspect({"tool": "Bash", "input": {"command": "set\necho done"}}, set())


class TestBuildReport:
    def run_report(self, tmp_path, entries, *rules):
        path = write_jsonl(tmp_path / "t.jsonl", entries)
        return rt.build_report([path], write_rules(tmp_path, *rules))

    def test_counts_matches_per_rule_and_dedupes_identical_calls(self, tmp_path):
        report = self.run_report(
            tmp_path,
            [
                tool_use("t1", "Bash", {"command": "cat a"}),
                tool_use("t2", "Bash", {"command": "cat a"}),
                tool_use("t3", "Bash", {"command": "cat b"}),
            ],
            WARN_RULE,
        )
        rule = report["rules"]["warn-test-cat"]
        assert rule["hits"] == 3
        assert [e["command"] for e in rule["examples"]] == ["cat a", "cat b"]
        assert rule["examples"][0]["count"] == 2

    def test_rules_that_never_match_are_listed_with_zero_hits(self, tmp_path):
        report = self.run_report(tmp_path, [tool_use("t1", "Bash", {"command": "ls"})], BLOCK_RULE)
        assert report["rules"]["block-test-dump"]["hits"] == 0

    def test_fired_in_log_but_not_now_is_reported_as_stopped(self, tmp_path):
        report = self.run_report(
            tmp_path,
            [
                tool_use("t1", "Bash", {"command": "ls"}),
                post_hook("t1", "warn-test-cat"),
            ],
            WARN_RULE,
        )
        assert [e["command"] for e in report["rules"]["warn-test-cat"]["stopped"]] == ["ls"]

    def test_matches_now_but_not_in_log_is_reported_as_started(self, tmp_path):
        report = self.run_report(tmp_path, [tool_use("t1", "Bash", {"command": "cat a"})], WARN_RULE)
        assert [e["command"] for e in report["rules"]["warn-test-cat"]["started"]] == ["cat a"]

    def test_rules_not_loaded_are_ignored_in_drift(self, tmp_path):
        report = self.run_report(
            tmp_path,
            [
                tool_use("t1", "Bash", {"command": "ls"}),
                post_hook("t1", "warn-other-project"),
            ],
            WARN_RULE,
        )
        assert "warn-other-project" not in report["rules"]

    def test_examples_mask_secrets_in_commands(self, tmp_path):
        report = self.run_report(
            tmp_path,
            [
                tool_use("t1", "Bash", {"command": "cat a; echo " + FAKE_GH}),
            ],
            WARN_RULE,
        )
        shown = report["rules"]["warn-test-cat"]["examples"][0]["command"]
        assert FAKE_GH not in shown

    def test_suspects_are_collected(self, tmp_path):
        report = self.run_report(tmp_path, [tool_use("t1", "Bash", {"command": "cat ~/.ssh/id_rsa"})], BLOCK_RULE)
        assert [s["command"] for s in report["suspects"]] == ["cat ~/.ssh/id_rsa"]

    def test_warn_rules_skip_drift_when_a_block_stopped_the_call(self, tmp_path):
        report = self.run_report(
            tmp_path,
            [
                tool_use("t1", "Bash", {"command": "cat dumpall"}),
                tool_result("t1", "PreToolUse:Bash hook error: **[block-test-dump]**\nblocked"),
            ],
            BLOCK_RULE,
            WARN_RULE,
        )
        assert report["rules"]["warn-test-cat"]["started"] == []
        assert report["rules"]["block-test-dump"]["started"] == []

    def test_hook_timeouts_are_listed(self, tmp_path):
        report = self.run_report(
            tmp_path,
            [
                tool_use("t1", "Bash", {"command": "slow thing"}),
                timeout_entry("t1"),
            ],
            BLOCK_RULE,
        )
        assert [t["command"] for t in report["timeouts"]] == ["slow thing"]

    def test_suspect_total_counts_past_the_cap(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rt, "MAX_SUSPECTS", 1)
        report = self.run_report(
            tmp_path,
            [
                tool_use("t1", "Bash", {"command": "cat ~/.ssh/id_rsa"}),
                tool_use("t2", "Bash", {"command": "cat ~/.aws/credentials"}),
            ],
            BLOCK_RULE,
        )
        assert len(report["suspects"]) == 1
        assert report["suspects_total"] == 2

    def test_long_commands_are_truncated(self, tmp_path):
        report = self.run_report(tmp_path, [tool_use("t1", "Bash", {"command": "cat " + "x" * 5000})], WARN_RULE)
        assert len(report["rules"]["warn-test-cat"]["examples"][0]["command"]) <= rt.MAX_SHOWN + 20


class TestRedact:
    def test_redacts_known_token_shapes(self):
        shown = rt.redact("echo " + FAKE_GH + " x")
        assert FAKE_GH not in shown

    def test_redacts_secret_named_assignments(self):
        shown = rt.redact("export API_TOKEN=abc123secretvalue; DB_PASSWORD='hunter2hunter2' ls")
        assert "abc123secretvalue" not in shown
        assert "hunter2hunter2" not in shown
        assert "API_TOKEN=" in shown

    def test_redacts_private_key_blocks(self):
        shown = rt.redact("-----BEGIN OPENSSH " + "PRIVATE KEY-----\nAAAAB3Nza\n-----END OPENSSH " + "PRIVATE KEY-----")
        assert "AAAAB3Nza" not in shown

    def test_long_keyword_runs_redact_in_linear_time(self):
        start = time.perf_counter()
        rt.redact("pass" * 15000)
        rt.redact("token" * 12000 + "=x")
        rt.redact('"' + "token" * 12000)
        rt.redact("mysql " * 10000)
        assert time.perf_counter() - start < 0.5

    @pytest.mark.parametrize(
        "text",
        [
            "BYPASS=1",
            "compass=north",
            "CLAUDE_CODE_MAX_OUTPUT_TOKENS=32000",
            "--passes=3",
            "max_tokens: 4096",
            "SSH_PASSPHRASE_FILE=/run/x",
            "GITHUB_TOKEN_PATH=/run/y",
            "pat=/y",
            "uses Basic authentication here",
        ],
    )
    def test_leaves_harmless_lookalikes_alone(self, text):
        assert rt.redact(text) == text

    def test_leaves_variable_references_alone(self):
        assert rt.redact('echo "$API_TOKEN" TOKEN=$X') == 'echo "$API_TOKEN" TOKEN=$X'

    # Built at runtime so gitleaks does not flag the fakes
    SHAPES: ClassVar[dict] = {
        "jwt": (
            "jwt=" + "ey" + "JhbGciOiJIUzI1NiJ9" + "." + "ey" + "JzdWIiOiIxMjMifQ" + ".c2lnbmF0dXJlc2ln",
            "c2lnbmF0dXJlc2ln",
        ),
        "bearer": ("header 'Authorization" + ": Bearer opaquevalue1234'", "opaquevalue1234"),
        "url-userinfo": ("git clone https://bob:" + FAKE + "@example.com/r", FAKE),
        "password-flag": ("mysql --password " + FAKE, FAKE),
        "token-flag-equals": ("tool --token=" + FAKE, FAKE),
        "json-key": ('{"api_token": "' + FAKE + '"}', FAKE),
        "quoted-with-spaces": ("PASSWORD='hunter2 pass word' run", "pass word"),
        "api-key-header": ("header 'X-Api-Key" + ": " + FAKE + "'", FAKE),
        "google": ("key=" + "AIza" + "B" * 35, "B" * 35),
        "stripe": ("k " + "sk_" + "live_" + "C" * 24, "C" * 24),
        "npm": ("t " + "npm_" + "D" * 36, "D" * 36),
        "auth-token-scheme": ("header 'Authorization" + ": token " + FAKE + "'", FAKE),
        "mysql-short-flag": ("mysql -uroot -p" + FAKE + " db", FAKE),
        "aws-secret": ("echo " + "wJalrXUtnFEMI/K7MDENG/" + "bPxRfiCYEXAMPLEKEY", "bPxRfiCYEXAMPLEKEY"),
        "json-escaped-quote": ('{"password": "ab\\"' + FAKE + '"}', FAKE),
        "passphrase": ("PASSPHRASE=" + FAKE, FAKE),
        "pgpass": ("PGPASS=" + FAKE, FAKE),
        "camel-case": ("apiToken=" + FAKE, FAKE),
        "pat-suffix": ("GH_PAT=" + FAKE, FAKE),
        "plural-name": ("API_TOKENS=" + FAKE, FAKE),
        "digit-suffix": ("AUTH_TOKEN2=" + FAKE, FAKE),
        "joined-suffix": ("DJANGO_SECRETKEY=" + FAKE, FAKE),
        "long-prefix": ("NEXT_PUBLIC_SUPABASE_SERVICE_ROLE_SECRET=" + FAKE, FAKE),
        "lowercase-bearer": ("Bearer " + "q" * 24, "q" * 24),
        "digits-then-punctuation": ("DB_PASSWORD=2024!" + FAKE, FAKE),
        "all-digit-password": ("DB_PASSWORD=831597", "831597"),
        "all-digit-pin": ("SIM_PIN_PASSWORD=4821", "4821"),
        "account-is-not-a-count": ("SERVICE_ACCOUNT_PASSWORD=831597", "831597"),
        "discount-is-not-a-count": ("DISCOUNT_SECRET=831597", "831597"),
        "long-number-under-max": ("MAX_API_KEY=" + "7" * 20, "7" * 20),
    }

    @pytest.mark.parametrize("shape", sorted(SHAPES))
    def test_redacts_common_secret_shapes(self, shape):
        text, secret = self.SHAPES[shape]
        assert secret not in rt.redact(text)


class TestWriteReport:
    def test_planted_symlinks_are_not_followed(self, tmp_path):
        out = tmp_path / "out"
        out.mkdir()
        target = tmp_path / "victim"
        target.write_text("keep")
        (out / "report.md").symlink_to(target)
        with pytest.raises(OSError):  # noqa: PT011
            rt.write_report(EMPTY_REPORT, str(out))
        assert target.read_text() == "keep"

    def test_refuses_a_folder_owned_by_someone_else(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rt.os, "getuid", lambda: os.stat(tmp_path).st_uid + 1)
        with pytest.raises(PermissionError):
            rt.write_report(EMPTY_REPORT, str(tmp_path))
        assert not (tmp_path / "report.md").exists()

    def test_existing_out_folder_permissions_are_left_alone(self, tmp_path):
        out = tmp_path / "shared"
        out.mkdir(mode=0o755)
        out.chmod(0o755)
        rt.write_report(EMPTY_REPORT, str(out))
        assert out.stat().st_mode & 0o777 == 0o755
        assert (out / "report.md").stat().st_mode & 0o777 == 0o600

    def test_report_folder_and_files_are_private(self, tmp_path):
        out = tmp_path / "out"
        rt.write_report(EMPTY_REPORT, str(out))
        assert out.stat().st_mode & 0o777 == 0o700
        for name in ("report.json", "report.md"):
            assert (out / name).stat().st_mode & 0o777 == 0o600


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
