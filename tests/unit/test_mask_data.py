#!/usr/bin/env python3
"""Unit tests for mask_data: blanking non-executing text before matching."""

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO_ROOT, "hookify-plus"))

from core.config_loader import Condition, Rule, extract_frontmatter
from core.masking import mask_data
from core.rule_engine import RuleEngine


class TestHeredocMasking:
    def test_quoted_heredoc_body_to_cat_is_blanked(self):
        cmd = "cat > /tmp/body.md <<'EOF'\nWe set `env` here\nEOF"
        assert "env" not in mask_data(cmd).split("<<'EOF'")[1].replace("EOF", "")

    def test_unquoted_heredoc_keeps_only_expansions(self):
        cmd = "cat <<EOF\nprose set here $GITHUB_TOKEN and $(env)\nEOF"
        masked = mask_data(cmd)
        assert "$GITHUB_TOKEN" in masked
        assert "$(env)" in masked
        assert "prose" not in masked

    def test_heredoc_to_interpreter_is_untouched(self):
        cmd = "bash <<'EOF'\nenv\nEOF"
        assert mask_data(cmd) == cmd

    def test_heredoc_piped_to_shell_is_untouched(self):
        cmd = "cat <<'EOF' | sh\nenv\nEOF"
        assert mask_data(cmd) == cmd

    def test_heredoc_to_source_is_untouched(self):
        cmd = "source /dev/stdin <<'EOF'\nenv\nEOF"
        assert mask_data(cmd) == cmd

    def test_commands_after_heredoc_are_kept(self):
        cmd = "cat > /tmp/x <<'EOF'\nhello\nEOF\nenv"
        assert mask_data(cmd).endswith("EOF\nenv")


class TestMessageArgMasking:
    def test_single_quoted_gh_body_is_blanked(self):
        assert "set" not in mask_data("gh issue comment 5 --body 'Value is set'")

    def test_double_quoted_gh_body_keeps_expansions(self):
        masked = mask_data('gh pr create --title "set it" --body "run `env` and $GITHUB_TOKEN"')
        assert "`env`" in masked
        assert "$GITHUB_TOKEN" in masked
        assert "run" not in masked

    def test_double_quoted_body_with_nested_quotes_is_untouched(self):
        cmd = 'gh pr create --body "$(cat ".env")"'
        assert mask_data(cmd) == cmd

    def test_git_commit_message_is_masked(self):
        assert "set" not in mask_data('git commit -m "chore: set executable file modes"')

    def test_message_flag_on_other_tools_is_untouched(self):
        cmd = 'kubectl run x -m "set"'
        assert mask_data(cmd) == cmd

    def test_commands_chained_after_message_are_kept(self):
        assert mask_data('git commit -m "fix: x" && env').endswith("&& env")


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

    def test_engine_masks_only_when_rule_opts_in(self):
        data = {"tool_name": "Bash", "tool_input": {"command": 'git commit -m "fix: set x"'}}
        engine = RuleEngine()
        assert engine._rule_matches(self._rule(False), data)
        assert not engine._rule_matches(self._rule(True), data)
