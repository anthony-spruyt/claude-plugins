#!/usr/bin/env python3
"""Unit tests for the rule fuzzer."""

import math
import os
import random
import shutil
import signal
import sys
import threading
import time

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

    def test_a_hanging_rule_is_cut_off_and_reported(self, tmp_path, monkeypatch):
        class Hangs:
            def _rule_matches(self, rule, data):
                time.sleep(5)
        monkeypatch.setattr(fz, "RuleEngine", Hangs)
        rules = rules_from(tmp_path, BLOCK_ENV)
        start = time.monotonic()
        slow = fz.slow_rules(rules, "x", limit=0.1, cap=0.3)
        assert time.monotonic() - start < 2
        assert [name for _, name in slow] == ["block-test-env"]


class TestTimeout:
    def test_an_outer_timer_survives(self):
        previous = signal.signal(signal.SIGALRM, lambda *_: None)
        signal.setitimer(signal.ITIMER_REAL, 30)
        try:
            fz._with_timeout(1, lambda: None)
            assert signal.getitimer(signal.ITIMER_REAL)[0] > 25
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)

    def test_off_the_main_thread_a_clean_parse_is_not_a_crash(self):
        result = []
        worker = threading.Thread(target=lambda: result.append(fz.crash_key("git status")))
        worker.start()
        worker.join()
        assert result == [None]


class TestCrash:
    def test_returns_none_when_parse_succeeds(self):
        assert fz.crash_key("git status") is None

    def test_returns_error_type_and_deepest_file_and_line(self, monkeypatch):
        def boom(_):
            raise ValueError("x")
        monkeypatch.setattr(fz, "normalise", boom)
        kind, where = fz.crash_key("anything")
        assert kind == "ValueError"
        assert where.startswith("test_fuzz_rules.py:")

    def test_a_hang_is_reported_as_a_timeout(self, monkeypatch):
        monkeypatch.setattr(fz, "normalise", lambda _: time.sleep(5))
        monkeypatch.setattr(fz, "CRASH_TIMEOUT", 0.2)
        start = time.monotonic()
        assert fz.crash_key("anything")[0] == "Timeout"
        assert time.monotonic() - start < 2

    def test_printed_crashes_are_redacted(self, monkeypatch, capsys):
        def boom(_):
            raise ValueError("x")
        monkeypatch.setattr(fz, "normalise", boom)
        token = "ghp_" + "Q" * 36
        fz.run_crash(["curl -H 'x: " + token + "'"], random.Random(1), 0)
        assert token not in capsys.readouterr().out


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

    @pytest.mark.parametrize("command", [
        "git init; gh pr merge 1",
        "timeout 5 git init",
        "nohup git init",
        "echo init | xargs git",
        "bash -c 'git init'",
        "find . -maxdepth 0 -exec git init \\;",
        "command git init",
    ])
    def test_real_git_never_runs_even_through_wrappers(self, tmp_path, command):
        fz.bypass_kind(command, [], str(tmp_path))
        assert not (tmp_path / ".git").exists()

    def test_secret_sent_into_git_or_gh_text_is_a_persist(self, tmp_path):
        assert fz.bypass_kind('gh pr create --title x --body "$SECRET_TOKEN"', [], str(tmp_path)) == "persist"

    @pytest.mark.skipif(not fz.sandbox_available(), reason="bwrap sandbox not usable here")
    def test_sandbox_blocks_writes_outside_the_work_dir(self, tmp_path):
        work = tmp_path / "work"
        work.mkdir()
        fz.bypass_kind("touch ../escaped", [], str(work))
        assert not (tmp_path / "escaped").exists()


@pytest.mark.skipif(not shutil.which("bwrap"), reason="needs bwrap")
class TestSandboxFailure:
    @pytest.fixture(autouse=True)
    def broken_bwrap(self, monkeypatch):
        real = fz._bwrap_argv
        monkeypatch.setattr(fz, "_bwrap_argv", lambda *a: real(*a)[:1] + ["--no-such-flag"] + real(*a)[1:])
        probe = fz.sandbox_available
        probe.cache_clear()
        yield
        probe.cache_clear()

    def test_probe_uses_the_real_flags(self):
        assert fz.sandbox_available() is False

    def test_a_bwrap_error_at_run_time_is_raised_not_hidden(self, tmp_path, monkeypatch):
        monkeypatch.setattr(fz, "sandbox_available", lambda: True)
        with pytest.raises(RuntimeError, match="bwrap"):
            fz.bypass_kind("env", [], str(tmp_path))


class TestMain:
    def test_count_zero_runs_nothing(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["fuzz_rules.py", "bypass", "--count", "0"])
        with pytest.raises(SystemExit):
            fz.main()
        assert capsys.readouterr().out.startswith("0 commands run")
