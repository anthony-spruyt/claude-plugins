#!/usr/bin/env python3
"""Unit tests for mask_data: blanking prose in gh/git message arguments."""

import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO_ROOT, "hookify-plus"))

from core.config_loader import Condition, Rule, extract_frontmatter
from core.masking import MAX_LENGTH, mask_data
from core.rule_engine import RuleEngine

PROSE = "We set `env` here"


class TestMasksMessageArguments:
    def test_single_quoted_body(self):
        assert "set" not in mask_data("gh issue comment 5 --body 'Value is set'")

    def test_double_quoted_body_keeps_variables(self):
        masked = mask_data('gh pr create --title "set it" --body "uses $GITHUB_TOKEN here"')
        assert "$GITHUB_TOKEN" in masked
        assert "set it" not in masked
        assert "uses" not in masked

    def test_equals_form(self):
        assert "set" not in mask_data('gh pr edit 1 --body="Value is set"')

    def test_git_commit_message(self):
        assert "set" not in mask_data('git commit -m "chore: set executable file modes"')

    def test_git_dash_c_dir_commit(self):
        assert "set" not in mask_data('git -C /repo commit -m "chore: set modes"')

    def test_cat_heredoc_message(self):
        cmd = f"git commit -m \"$(cat <<'EOF'\nfix: x\n\n{PROSE}\nEOF\n)\""
        assert "env" not in mask_data(cmd)

    def test_stdin_heredoc_body(self):
        cmd = f"gh pr create --title x --body-file - <<'EOF'\n{PROSE}\nEOF"
        assert "env" not in mask_data(cmd)

    def test_only_message_segment_is_masked(self):
        cmd = f"git add -A && git commit -m \"$(cat <<'EOF'\n{PROSE}\nEOF\n)\" && git push"
        masked = mask_data(cmd)
        assert "env" not in masked
        assert masked.startswith("git add -A && git commit -m ")
        assert masked.endswith(" && git push")

    def test_cd_before_commit(self):
        assert "set" not in mask_data("cd /repo && git commit -m 'chore: set modes'")

    def test_chained_command_after_message_is_kept(self):
        assert mask_data('git commit -m "fix: x" && env').endswith("&& env")


@pytest.mark.parametrize("cmd", [
    f"cat > /tmp/s <<'EOF'\n{PROSE}\nEOF",
    f"bash <<'EOF'\n{PROSE}\nEOF",
    f"gh pr create --body-file - <<EOF\n{PROSE}\nEOF",
    "kubectl run x -m 'set'",
    "git -c alias.x='!sh' x -m 'set'",
    "git status && sh -c 'eval \"$1\"' -m 'set'",
    "git log -m 'set'",
], ids=["heredoc-to-cat", "heredoc-to-bash", "unquoted-delimiter",
        "not-gh-or-git", "git-config-override", "git-earlier-on-line", "git-non-message"])
def test_leaves_non_message_text_alone(cmd):
    assert mask_data(cmd) == cmd


@pytest.mark.parametrize("cmd", [
    "git commit -m 'set' \\\n&& env",
    "echo $((1<<2)) && git commit -m 'set'",
    "git commit -m 'set' # note",
    "git commit -m 'set' | sh",
    "git commit -m 'set' > /tmp/out",
    "git commit -m 'set' 2>&1",
    'gh issue comment 5 --body "Never run `env`"',
    'git commit -m "$(env)"',
    'gh pr create --body "$( $(echo env) )"',
    'gh pr create --body "$(case x in x) env;; esac)"',
    'git commit -m "costs $5"',
    "git commit -m 'unterminated",
    "git commit -F - <<'EOF'\nno terminator",
    "cat <<<'EOF'\nset\nEOF",
    "git commit -m \"$(cat <<'EOF'\nx\nEOF)\"\necho PWNED\n: \"\nEOF\n)\"",
    "git commit -m \"$(cat <<'EOF'\nx\nEOF )\"; echo PWNED; : \"\nEOF\n)\"",
    "git commit -F - <<'E'\"OF\"\nx\nEOF\necho PWNED\nE",
    "git commit -F - <<'E'OF\nx\nEOF\necho PWNED\nE",
    "alias git=eval; shopt -s expand_aliases\ngit commit -m ';echo PWNED'",
    "eval 'git(){ eval \"$3\"; }'; git commit -m 'echo PWNED'",
    "unalias git; git commit -m 'set'",
    "git commit -m '$(echo PWNED)'; git commit -m \"${_@P}\"",
    "git commit -m 'x[$(echo PWNED)]'; git commit -m \"${!_}\"",
    "git commit -m \"${x:-set}\"",
    "gh release create v1 --target -b .env",
    "gh release create v1 -R o/r --discussion-category -t ~/.aws/credentials",
    "gh release create v1 -- -t .env",
    "gh release create v1 --notes x .env",
    "gh pr create --unknown-flag -b 'set'",
    "gh pr create -b'set'",
    "git commit --pathspec-from-file -m 'set'",
], ids=["line-continuation", "arithmetic", "comment", "pipe", "redirect", "fd-redirect",
        "backtick", "command-substitution", "nested-substitution", "case-in-substitution",
        "positional-param", "unterminated-quote", "unterminated-heredoc", "here-string",
        "paren-after-delimiter", "space-paren-after-delimiter", "glued-delimiter-double",
        "glued-delimiter-bare", "alias-redefines-git", "eval-redefines-git", "other-command-first",
        "prompt-expansion-of-last-arg", "indirect-last-arg", "parameter-operator",
        "message-flag-as-value", "message-flag-as-value-long", "end-of-options",
        "release-asset", "unknown-flag", "glued-message-value", "unknown-git-flag"])
def test_gives_up_on_anything_it_cannot_parse(cmd):
    assert mask_data(cmd) == cmd


@pytest.mark.parametrize("cmd", [
    'git commit -am "chore: set modes"',
    'git tag -a v1 -m "set things"',
    'gh pr create --base main --head feat --title "fix: set x" --body "env is set" --draft',
    'gh pr merge 5 --squash --subject "fix: set x" --body "env set"',
    'gh issue create --title "set is noisy" --body "env" --label bug --repo o/r',
    'gh release create v1.2.0 --title "v1.2.0" --notes "env and set fixes" --latest',
    'gh pr close 5 --comment "env set"',
], ids=["combined-short-flags", "annotated-tag", "pr-create-flags", "pr-merge-squash",
        "issue-create-flags", "release-create", "pr-close-comment"])
def test_masks_messages_among_known_flags(cmd):
    masked = mask_data(cmd)
    assert "set" not in masked.replace("--subject", "")
    assert "env" not in masked


def test_gives_up_on_long_commands():
    cmd = "git commit -m '" + "set " * (MAX_LENGTH // 4) + "'"
    assert mask_data(cmd) == cmd


class TestRuleOptIn:
    def test_mask_data_parsed_from_frontmatter(self):
        fm, msg = extract_frontmatter("---\nname: r\nevent: bash\npattern: x\nmask_data: true\n---\nm")
        assert Rule.from_dict(fm, msg).mask_data is True

    def test_mask_data_defaults_false(self):
        fm, msg = extract_frontmatter("---\nname: r\nevent: bash\npattern: x\n---\nm")
        assert Rule.from_dict(fm, msg).mask_data is False

    def _rule(self, mask):
        return Rule(name="r", enabled=True, event="bash", action="block", mask_data=mask,
                    conditions=[Condition("command", "regex_match", r"\bset\b")])

    def _data(self, tool="Bash"):
        return {"tool_name": tool, "tool_input": {"command": 'git commit -m "fix: set x"'}}

    def test_engine_masks_only_when_rule_opts_in(self):
        engine = RuleEngine()
        assert engine._rule_matches(self._rule(False), self._data())
        assert not engine._rule_matches(self._rule(True), self._data())

    @pytest.mark.parametrize("tool", ["PowerShell", "Monitor", "mcp__x__run"])
    def test_engine_masks_bash_only(self, tool):
        assert RuleEngine()._rule_matches(self._rule(True), self._data(tool))
