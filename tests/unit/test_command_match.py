#!/usr/bin/env python3
"""Unit tests for the command_match operator and its fallback."""

import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO_ROOT, "hookify-plus"))

from core import rule_engine
from core.config_loader import Condition, Rule, extract_frontmatter
from core.globbing import MAX_ENTRIES
from core.rule_engine import RuleEngine
from core.shell_parse import normalise

PATTERN = r"^(env|printenv)( -\S+)*$"
NASTY = r"""(?:^|[;&|]\s*)(?:env|printenv)\b(?![:#])[^'"\\|]*(?:\\.|'[^']*'|"x")*$ # not:a comment|---"""


def _yaml_single(text):
    return "'" + text.replace("'", "''") + "'"


def _frontmatter(conditions_yaml):
    content = "---\nname: r\nevent: bash\naction: block\nconditions:\n" + conditions_yaml + "---\nmsg"
    return Rule.from_dict(*extract_frontmatter(content))


class TestFrontmatter:
    def test_fallback_round_trips(self):
        rule = _frontmatter(
            "  - field: command\n"
            "    operator: command_match\n"
            f"    pattern: {_yaml_single(PATTERN)}\n"
            f"    fallback: {_yaml_single(NASTY)}\n"
        )
        cond = rule.conditions[0]
        assert cond.operator == "command_match"
        assert cond.pattern == PATTERN
        assert cond.fallback == NASTY

    def test_quoted_pattern_with_comma_on_dash_line(self):
        rule = _frontmatter(f"  - pattern: {_yaml_single('x{1,3}: y')}\n    field: command\n")
        assert rule.conditions[0].pattern == "x{1,3}: y"
        assert rule.conditions[0].field == "command"

    def test_missing_fallback_is_none(self):
        rule = _frontmatter("  - field: command\n    operator: command_match\n    pattern: x\n")
        assert rule.conditions[0].fallback is None

    def test_double_quoted_value_keeps_backslashes(self):
        rule = _frontmatter('  - field: command\n    pattern: "a\\\\s#b"\n')
        assert rule.conditions[0].pattern == "a\\\\s#b"


def _rule(pattern=PATTERN, fallback=None, mask=False, operator="command_match", field="command"):
    return Rule(
        name="r",
        enabled=True,
        event="bash",
        action="block",
        mask_data=mask,
        conditions=[Condition(field, operator, pattern, fallback)],
    )


def _matches(rule, command, tool="Bash"):
    return RuleEngine()._rule_matches(rule, {"tool_name": tool, "tool_input": {"command": command}})


class TestCleanLines:
    @pytest.mark.parametrize("cmd", ["env", "e''nv", "sudo -E e''nv", "bash -c 'printenv -0'"])
    def test_matches_after_quote_removal(self, cmd):
        assert _matches(_rule(), cmd)

    def test_clean_lines_keep_pipes(self):
        assert not _matches(_rule(), "e''nv | wc -l")
        assert _matches(_rule(pattern=r"^env( \| .*)?$"), "sudo -E e''nv | wc -l")

    @pytest.mark.parametrize("cmd", ["cd env", 'grep -E "(export|import)" f', "echo env"])
    def test_ignores_non_invocations(self, cmd):
        assert not _matches(_rule(), cmd)

    def test_regex_is_case_insensitive(self):
        assert _matches(_rule(), "ENV")


class TestUnparseable:
    CMD = "$X env"

    def test_command_really_is_unparseable(self):
        assert normalise(self.CMD) is None

    def test_uses_fallback(self):
        assert _matches(_rule(fallback=r"\$X\s+env\b"), self.CMD)
        assert not _matches(_rule(fallback=r"printenv"), self.CMD)

    def test_without_fallback_uses_pattern_on_raw_command(self):
        assert not _matches(_rule(), self.CMD)
        assert _matches(_rule(pattern=r"\benv$"), self.CMD)


class TestUnparseableSegments:
    @pytest.mark.parametrize(
        "cmd",
        [
            "n=$((1)); env",
            "n=$((1)) && sudo env -0",
            "case x in x) env;; esac",
            "n=$((1)); if true; then e''nv; fi",
            "n=$((1)); echo x | env",
        ],
    )
    def test_block_rule_matches_pattern_on_each_segment(self, cmd):
        assert normalise(cmd) is None
        assert _matches(_rule(fallback=r"nomatch"), cmd)

    def test_warn_rule_keeps_fallback_only(self):
        rule = _rule(fallback=r"nomatch")
        rule.action = "warn"
        assert not _matches(rule, "n=$((1)); env")

    def test_segments_share_one_glob_budget(self, tmp_path, monkeypatch):
        for n in range(MAX_ENTRIES // 4):
            (tmp_path / str(n)).touch()
        monkeypatch.chdir(tmp_path)
        rule_engine.segment_lines.cache_clear()
        _, overflow = rule_engine.segment_lines("n=$((1)); " + "; ".join(["ls 7?"] * 8), str(tmp_path))
        assert overflow

    @pytest.mark.parametrize("cmd", ["n=$((1)); echo env", "case x in x) cd env;; esac"])
    def test_segments_keep_the_pattern_anchor(self, cmd):
        assert not _matches(_rule(fallback=r"nomatch"), cmd)


class TestMasking:
    def test_command_match_sees_quote_removed_command(self):
        assert _matches(_rule(pattern=r"--body env$"), 'gh pr create --body "e""nv"')

    def test_masked_rule_does_not_see_message_text(self):
        assert not _matches(_rule(pattern=r"--body env$", mask=True), 'gh pr create --body "env"')

    def test_prose_does_not_match_invocation_pattern(self):
        assert not _matches(_rule(mask=True), 'gh pr create --body "env"')

    def test_fallback_sees_masked_command(self, monkeypatch):
        # No real command is both maskable and unparseable, so force the parser to give up.
        monkeypatch.setattr(rule_engine, "normalise", lambda command: None)
        rule_engine.clean_lines.cache_clear()
        cmd = 'gh pr create --body "env"'
        assert not _matches(_rule(fallback=r"\benv\b", mask=True), cmd)
        assert _matches(_rule(fallback=r"\benv\b", mask=False), cmd)
        rule_engine.clean_lines.cache_clear()


class TestParserCrash:
    def test_exception_uses_fallback(self, monkeypatch):
        def boom(command):
            raise IndexError

        monkeypatch.setattr(rule_engine, "normalise", boom)
        rule_engine.clean_lines.cache_clear()
        try:
            assert _matches(_rule(fallback=r"\bboom\b"), "x; boom")
            assert not _matches(_rule(fallback=r"nomatch"), "x; boom")
        finally:
            rule_engine.clean_lines.cache_clear()


class TestOpaqueAlsoUsesFallback:
    FALLBACK = r"\bprintenv\b"

    @pytest.mark.parametrize(
        "cmd",
        [
            "echo printenv | cat | sh",
            "bash < <(echo printenv)",
            "echo printenv | xargs nice",
            "trap printenv EXIT",
            "busybox printenv",
            "docker exec c printenv",
            "kubectl exec p -- printenv",
            "tmux new printenv",
            "find /usr/bin -name printenv -exec {} \\;",
            "PS4='$(printenv)' bash -xc :",
            "source ./printenv.sh",
            "git -c alias.x='!f(){ eval \"$2\"; }; f' x -m printenv",
            "git -c 'alias.y=!printenv' y",
            "git config alias.z '!printenv'",
            "cat <<'EOF' | ash\nprintenv\nEOF",
            "cat > s <<'EOF'\nprintenv\nEOF\nbash s",
            "cat <<'EOF' >> ~/.bashrc\nprintenv\nEOF",
            "echo printenv > run.sh",
            "printf 'printenv' >> ~/.bashrc",
            "echo printenv | ssh host",
            "echo printenv | tee x | bash",
            "parallel ::: printenv",
        ],
    )
    def test_opaque_command_also_checks_fallback(self, cmd):
        assert normalise(cmd) is not None
        assert _matches(_rule(pattern=r"^nomatch$", fallback=self.FALLBACK), cmd)

    @pytest.mark.parametrize("cmd", ["echo printenv", "mkdir -p printenv # x", "git log printenv"])
    def test_plain_commands_skip_fallback(self, cmd):
        assert not _matches(_rule(pattern=r"^nomatch$", fallback=self.FALLBACK), cmd)


class TestMaskedCleanLines:
    NAME = r"\.npmrc\b"

    def test_message_text_is_masked_in_clean_lines(self):
        rule = _rule(pattern=self.NAME, fallback=self.NAME, mask=True)
        assert not _matches(rule, 'git commit -m "docs: ignore .npmrc"')

    def test_unwrapped_message_is_masked(self):
        rule = _rule(pattern=r"^git .*\.npmrc\b", mask=True)
        assert not _matches(rule, "bash -c 'git commit -m \"docs: ignore .npmrc\"'")

    def test_real_reads_still_match(self):
        rule = _rule(pattern=self.NAME, fallback=self.NAME, mask=True)
        assert _matches(rule, "c''at ~/.np''mrc")
        assert _matches(rule, 'git commit -m "x" && cat ~/.npmrc')

    def test_unmasked_rule_sees_message_text(self):
        assert _matches(_rule(pattern=self.NAME), 'git commit -m "docs: ignore .npmrc"')


class TestPowerShell:
    def test_uses_fallback_not_bash_parser(self):
        rule = _rule(pattern=r"^cat ", fallback=r"\bGet-Content\b")
        assert _matches(rule, "Get-Content secrets.txt", tool="PowerShell")
        assert not _matches(rule, "cat x", tool="PowerShell")


class TestOtherFields:
    def test_non_command_field_is_plain_regex(self):
        rule = _rule(pattern=r"\.env$", field="file_path")
        data = {"tool_name": "Read", "tool_input": {"file_path": "/a/.env"}}
        assert RuleEngine()._rule_matches(rule, data)


def test_unknown_operator_still_false():
    assert not _matches(_rule(pattern="env", operator="no_such_op"), "env")


def test_regex_condition_without_fallback_arg():
    assert Condition("command", "regex_match", "x").fallback is None


class TestGlobOverflow:
    def _rule(self):
        return _rule(pattern="", operator="glob_overflow")

    @pytest.mark.parametrize("cmd", ["echo {1..300}", "n=$((1)); echo {1..300}", "bash -c 'echo {1..300}'"])
    def test_matches_word_past_the_limits(self, cmd):
        assert _matches(self._rule(), cmd)

    @pytest.mark.parametrize("cmd", ["echo {1..3}", "echo '{1..300}'", "n=$((1)); echo x"])
    def test_ignores_small_or_quoted_words(self, cmd):
        assert not _matches(self._rule(), cmd)

    def test_other_tools_never_match(self):
        assert not _matches(self._rule(), "echo {1..300}", tool="PowerShell")
