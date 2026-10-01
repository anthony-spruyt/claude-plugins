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
    "docker-exec-spaces": "docker exec" + " " * 19000 + "; e" + "nv",
    "then-spaces": "echo then" + " " * 19000,
    "ssh-spaces": "ssh a" + " " * 19000,
    "many-docker-execs": "docker exec " * 1600,
    "unclosed-quote-echos": 'echo "' + "echo " * 4000,
    "many-subshells": "echo $(" * 3000,
    "many-here-strings": "cat <<< " * 2500,
    "many-dollars-in-heredoc": "cat <<A\n" + "$ " * 9000,
    "backslash-echos": "\\echo " * 3000,
    "long-heredoc-delimiter": "git commit -F - <<'" + "A" * 10000 + "'\nx\n" + "A" * 9900,
    "unclosed-braces": "echo " + "${A_" * 5000,
    "echo-dollar-braces": ("echo ${" * 3000)[:20000],
    "assignment-substitutions": "a=$(" * 5000,
    "assignment-quotes": 'a="' * 6600,
}


def _fastest(engine, rule, data):
    timings = []
    for _ in range(3):
        start = time.perf_counter()
        engine._rule_matches(rule, data)
        timings.append(time.perf_counter() - start)
    return min(timings)


# Quadratic patterns run for seconds here; 200ms leaves headroom for a loaded CI box
@pytest.mark.parametrize("name", INPUTS)
def test_rules_finish_quickly(name):
    data = {"tool_name": "Bash", "tool_input": {"command": INPUTS[name]}}
    engine = RuleEngine()
    for rule in RULES:
        elapsed = _fastest(engine, rule, data)
        assert elapsed < 0.2, f"{rule.name} took {elapsed * 1000:.0f}ms on {name}"
