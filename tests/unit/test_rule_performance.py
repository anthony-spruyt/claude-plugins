#!/usr/bin/env python3
"""Every security rule must stay fast on adversarial input - hooks run on each tool call."""

import glob
import os
import sys
import time

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO_ROOT, "hookify-plus"))

from core.config_loader import load_rule_file
from core.rule_engine import RuleEngine

RULES = [load_rule_file(f) for f in sorted(glob.glob(
    os.path.join(REPO_ROOT, "security-hooks", "hookify-plus", "*.md")))]

INPUTS = {
    "many-heredocs-one-line": "cat <<A " * 5000,
    "many-heredocs-multiline": "cat <<A\n" * 5000,
    "echo-then-spaces": "echo" + " " * 40000 + "x",
    "many-echos": "echo $( " * 5000,
    "many-cats": "cat " * 10000,
    "many-timeouts": "timeout " * 10000,
    "many-cron-fields": "* " * 20000,
    "many-commits": "git commit -m x;" * 1200,
    "many-commits-multiline": "git commit -m x\n" * 1200,
    "many-pr-creates": "gh pr create --body x && " * 800,
    "many-powershell-env": "$env:" * 4000,
    "many-assignments": "a=" * 10000,
    "many-path-segments": "a/" * 10000,
}


@pytest.mark.parametrize("name", INPUTS)
def test_rules_finish_quickly(name):
    data = {"tool_name": "Bash", "tool_input": {"command": INPUTS[name]}}
    engine = RuleEngine()
    for rule in RULES:
        start = time.perf_counter()
        engine._rule_matches(rule, data)
        elapsed = time.perf_counter() - start
        assert elapsed < 0.05, f"{rule.name} took {elapsed * 1000:.0f}ms on {name}"
