#!/usr/bin/env python3
"""command_match patterns run on every clean line - they must stay linear on adversarial input."""

import os
import re
import sys
import time

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO_ROOT, "hookify-plus"))

from core.config_loader import load_rule_file

RULE_NAMES = [
    "block-env-dump",
    "block-printenv",
    "block-env-grep",
    "block-set-dump",
    "block-export-dump",
    "block-declare-dump",
]

PATTERNS = {}
for _name in RULE_NAMES:
    _rule = load_rule_file(os.path.join(REPO_ROOT, "security-hooks", "hookify-plus", _name + ".md"))
    PATTERNS[_name] = re.compile(_rule.conditions[0].pattern, re.IGNORECASE | re.DOTALL)

# Built at runtime so this file doesn't trip the very hooks it tests.
E = "e" + "nv"
PE = "print" + E

INPUTS = {
    "env-split-assign": E + " -S A=1" * 14 + " x",
    "env-split-assign-20k": E + " -S A=1" * 2800 + " x",
    "env-dashdash-splits": E + " -- " + "-S " * 22 + "x",
    "env-dashdash-splits-20k": E + " -- " + "-S " * 6600 + "x",
    "env-split-then-env": E + " -S A=1" * 20 + "; " + E,
    "env-split-quoted-items": E + " '-S" + " A=1" * 5000 + " x'",
    "env-split-quoted-spaces": E + " '-S" + " " * 20000 + "x'",
    "env-split-unclosed": E + " -S '" + "A=1 " * 5000,
    "env-unset-args": E + " -u A" * 5000 + " x",
    "env-assignments": E + " A=1" * 5000 + " x",
    "env-long-options": E + " --debug" * 2500 + " x",
    "env-quoted-assignments": E + " 'A=1 2'" * 2500 + " x",
    "env-wc-flags": E + " | wc" + " -l" * 6000 + " x",
    "printenv-names": PE + " A" * 9000 + " > /dev/null x",
    "parallel-many-separators": "parallel " + "x ::: " * 3300 + "y",
    "parallel-spaces": "parallel ::: " + "a " * 9000 + "x",
    "declare-many-options": "declare" + " -a" * 6000 + " x",
    "declare-p-many-args": "declare -p" + " a" * 9000 + " 'x",
    "readonly-many-options": "readonly" + " -a" * 6000 + " x",
    "echo-pipe-many-words": "echo export | " + "a " * 9000 + "x",
    "echo-redirect-long-target": "echo export > " + "a" * 20000 + " x",
    "echo-pipe-slashes": "echo set | " + "a/" * 9000 + " x",
}


@pytest.mark.parametrize("rule", RULE_NAMES)
@pytest.mark.parametrize("label", sorted(INPUTS))
def test_pattern_is_fast(rule, label):
    regex, text = PATTERNS[rule], INPUTS[label]
    best = float("inf")
    for _ in range(3):
        start = time.perf_counter()
        regex.search(text)
        best = min(best, time.perf_counter() - start)
    assert best < 0.02, f"{rule} took {best * 1000:.1f} ms on {label}"
