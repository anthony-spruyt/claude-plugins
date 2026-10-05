#!/usr/bin/env python3
"""Unit tests for the rule fuzzer."""

import math
import os
import random
import shutil
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests", "helpers"))

import fuzz_rules as fz
import replay_transcripts as rt

BLOCK_ENV = """---
name: block-test-env
enabled: true
event: bash
conditions:
  - field: command
    operator: command_match
    pattern: '^env$'
    fallback: '\\benv\\b'
action: block
---
blocked
"""


def rules_from(tmp_path, *bodies):
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir(exist_ok=True)
    for i, body in enumerate(bodies):
        (rules_dir / f"r{i}.md").write_text(body)
    return rt.load_rule_dir(str(rules_dir))


class TestCorpus:
    def test_reads_commands_from_every_suite(self):
        corpus = fz.load_corpus()
        assert len(corpus) > 500
        assert all(isinstance(c, str) and c for c in corpus)

    def test_log_commands_are_added_and_deduped(self, tmp_path):
        log = tmp_path / "p" / "s.jsonl"
        log.parent.mkdir()
        entry = '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"t","name":"Bash","input":{"command":"zz-from-log"}}]}}'
        log.write_text(entry + "\n" + entry.replace('"t"', '"u"') + "\n")
        corpus = fz.load_corpus(logs_root=str(tmp_path))
        assert corpus.count("zz-from-log") == 1


class TestMutate:
    def test_same_seed_gives_same_mutation(self):
        corpus = ["git commit -m hi", "cat .env"]
        a = fz.mutate(corpus[0], random.Random(5), corpus)
        b = fz.mutate(corpus[0], random.Random(5), corpus)
        assert a == b

    def test_mutation_changes_the_input_sometimes(self):
        rng = random.Random(1)
        outs = {fz.mutate("git status", rng, ["git status"]) for _ in range(50)}
        assert len(outs) > 1


class TestSpeed:
    def test_reports_rules_over_the_limit(self, tmp_path):
        rules = rules_from(tmp_path, BLOCK_ENV)
        assert [name for _, name in fz.slow_rules(rules, "env", limit=-1)] == ["block-test-env"]

    def test_quiet_when_under_the_limit(self, tmp_path):
        rules = rules_from(tmp_path, BLOCK_ENV)
        assert fz.slow_rules(rules, "env", limit=math.inf) == []

    def test_repeat_unit_fills_to_the_length_cap(self):
        assert len(fz.repeat_unit("ab ", 1000)) == 1000


class TestCrash:
    def test_returns_none_when_parse_succeeds(self):
        assert fz.crash_key("git status") is None

    def test_returns_error_type_and_line_on_crash(self, monkeypatch):
        def boom(_):
            raise ValueError("x")
        monkeypatch.setattr(fz, "normalise", boom)
        kind, line = fz.crash_key("anything")
        assert kind == "ValueError" and isinstance(line, int)


@pytest.mark.skipif(not shutil.which("bash"), reason="needs bash")
class TestBypass:
    def test_env_dump_that_runs_unblocked_is_a_dump(self, tmp_path):
        assert fz.bypass_kind("env", [], str(tmp_path)) == "dump"

    def test_reading_the_env_file_is_a_dump(self, tmp_path):
        assert fz.bypass_kind("cat .env", [], str(tmp_path)) == "dump"

    def test_printing_the_value_is_a_print(self, tmp_path):
        assert fz.bypass_kind('echo "$SECRET_TOKEN"', [], str(tmp_path)) == "print"

    def test_value_run_as_a_command_is_an_error_echo(self, tmp_path):
        assert fz.bypass_kind("$SECRET_TOKEN", [], str(tmp_path)) == "error"

    def test_env_that_a_block_rule_catches_is_not_a_bypass(self, tmp_path):
        assert fz.bypass_kind("env", rules_from(tmp_path, BLOCK_ENV), str(tmp_path)) is None

    def test_command_that_never_leaks_is_not_a_bypass(self, tmp_path):
        assert fz.bypass_kind("echo hi", [], str(tmp_path)) is None

    def test_env_quoted_as_message_text_is_not_a_bypass(self, tmp_path):
        assert fz.bypass_kind("git commit -m 'env'", [], str(tmp_path)) is None

    def test_real_git_and_gh_never_run(self, tmp_path):
        assert fz.bypass_kind("git init; gh pr merge 1", [], str(tmp_path)) is None
        assert not (tmp_path / ".git").exists()
