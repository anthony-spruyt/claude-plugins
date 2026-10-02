"""PreToolUse must block, not allow, when evaluating block rules crashes."""

import io
import json
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLUGIN_ROOT = os.path.join(REPO_ROOT, "hookify-plus")
sys.path.insert(0, PLUGIN_ROOT)

from core.config_loader import Rule
from hooks import pretooluse


def run_hook(monkeypatch, rules, evaluate):
    monkeypatch.setattr(pretooluse, "load_rules", lambda event: rules)
    monkeypatch.setattr(pretooluse.RuleEngine, "evaluate_rules", evaluate)
    payload = {"tool_name": "Bash", "tool_input": {"command": "echo hi"}}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    with pytest.raises(SystemExit) as exit_info:
        pretooluse.main()
    return exit_info.value.code


def block_rule():
    return Rule.from_dict({"name": "r", "event": "bash", "action": "block", "pattern": "x"}, "")


def boom(self, rules, input_data):
    raise IndexError("list index out of range")


def test_crash_while_evaluating_block_rules_blocks(monkeypatch, capsys):
    assert run_hook(monkeypatch, [block_rule()], boom) == 2
    assert "list index out of range" in capsys.readouterr().err


def test_crash_with_no_block_rules_allows(monkeypatch):
    assert run_hook(monkeypatch, [], boom) == 0


def test_clean_allow_still_allows(monkeypatch):
    assert run_hook(monkeypatch, [block_rule()], lambda self, rules, data: {}) == 0
