#!/usr/bin/env python3
"""Every security rule must stay fast on adversarial input - hooks run on each tool call."""

import glob
import os
import sys
import time
from functools import partial

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO_ROOT, "hookify-plus"))

from core.config_loader import load_rule_file
from core.rule_engine import RuleEngine, clean_lines

RULES = [
    load_rule_file(f)
    for plugin in ("security-hooks", "best-practices")
    for f in sorted(glob.glob(os.path.join(REPO_ROOT, plugin, "hookify-plus", "*.md")))
]

# Quadratic patterns run for seconds here; 200ms leaves headroom for a loaded CI box
LIMIT = 0.2

# CPU time leaves out waiting for a CPU under xdist; a core shared with other workers still slows the work
CLOCK = time.thread_time

# Loose wall cap: work moved to another thread, a subprocess or a blocking call reads ~0 CPU time
WALL_FACTOR = 5

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
    "process-substitutions": ("<(" * 10000)[:19990],
    "bang-redirects": "!>" * 9990,
    "watch-flags": "watch -." * 2490,
    "watch-subshells": "watch -(" * 2490,
    "bang-assignments": "!a=" * 6600,
    "brace-assignments": "{a=" * 6600,
    "env-unset-flags": "e" + "nv" + " -u A=1" * 2800 + " x",
    "env-unset-env": ("e" + "nv -u ") * 2850,
    "env-split-string": ("e" + "nv -S '") * 2500,
    "paren-after-keywords": "if(" * 6600,
    "assignment-braces": "X=a{" * 5000,
    "many-echo-subshells": ("$(echo e" + "nv)") * 1700,
    "many-eval-echo-subshells": ('eval "$(echo e' + 'nv)"\n') * 1000,
    "many-and-or-echos": "$(true && echo set || echo x)" * 690,
    "many-backtick-echos": "echo `echo x` " * 1400,
    "many-quoted-echos": 'echo "echo x" ' * 1400,
    "assignment-close-braces": "X=a}" * 5000,
    "many-function-names": "f " * 10000,
    "many-git-global-options": "git" + " -a" * 6000 + " x",
    "many-gh-global-options": "gh" + " -a" * 6000 + " x",
    "printf-open-brace-dollars": "printf }{${A" * 1600,
    "echo-in-open-braces": "bash -c echo }Get-ChildItem ${A" * 645,
    "commit-many-substitutions": 'git commit -m "' + "$(a)" * 4900,
    "commit-open-substitutions": 'git commit -m "' + "$((" * 6600,
    "gh-body-many-dollars": "gh pr create --body " + "$ " * 9900,
    "gh-global-options-body": "gh" + " -a" * 6000 + " pr create --body $A_TOKEN",
    "gh-bodies-in-open-quote": (("'$" + "e" + "nv:X=gh pr create --body ") * 700)[:20000],
    "many-runners-then-secret": ("ev" + "al " * 6600)[:19990] + "x",
    "many-assignments-spaced": "a=1 " * 5000,
    "many-secrets-glued": ("$A_" + "TOKEN") * 1600,
    "many-dollars-after-pipes": "|$" * 9900,
    "escaped-separators-open-braces": "\\;${A" * 3300,
    "declare-n-many-names": "declare -n" + " a=b" * 4900,
    "declare-many-flags-n": "declare" + " -a" * 6000 + " -n",
    "indirect-bang-braces": "${!" * 6600,
    "prompt-expansion-braces": "${a" * 6600 + "@P}",
    "gpg-many-options": "gpg" + " --batch" * 2400 + " x",
    "gpg-many-short-flags": "gpg" + " -q" * 6000,
    "many-globs": "cat " + "*/ " * 6600,
    "many-brace-commas": "cat {" + "a," * 9900 + "}",
    "nested-brace-groups": "cat " + "{a,b}" * 3900,
    "brace-sequences": "cat " + "{1..9}" * 3300,
    "upload-many-ats": "curl -d " + "@" * 19000,
    "arithmetic-segments": "$((1));" * 2800,
    "arithmetic-then-words": "$((1)); " + "a " * 9900,
    "arithmetic-unclosed-quote": "$((1)); '" + ";" * 19900,
    "arithmetic-brace-words": "$((1)); " + "echo {1..300};" * 1300,
    "ps-many-flags": "ps" + " a" * 9990 + " x",
}


def assert_fast(work, limit, label, before=None):
    wall_limit = limit * WALL_FACTOR
    cpu_times, wall_times = [], []
    for _ in range(3):
        if before:
            before()
        cpu_start, wall_start = CLOCK(), time.perf_counter()
        work()
        cpu_times.append(CLOCK() - cpu_start)
        wall_times.append(time.perf_counter() - wall_start)
        if cpu_times[-1] < limit and wall_times[-1] < wall_limit:
            break
    cpu, wall = min(cpu_times), min(wall_times)
    message = f"{label} took {cpu * 1000:.0f}ms CPU, {wall * 1000:.0f}ms wall"
    assert cpu < limit, message
    assert wall < wall_limit, message


@pytest.mark.parametrize("name", INPUTS)
def test_rules_finish_quickly(name):
    data = {"tool_name": "Bash", "tool_input": {"command": INPUTS[name]}}
    engine = RuleEngine()
    for rule in RULES:
        work = partial(engine._rule_matches, rule, data)
        assert_fast(work, LIMIT, f"{rule.name} on {name}", clean_lines.cache_clear)


def _measure(work):
    start = CLOCK()
    work()
    return CLOCK() - start


def _burn_cpu():
    # Wall cap so a clock that never advances fails the test instead of hanging it
    began = time.perf_counter()
    cpu_start = CLOCK()
    while CLOCK() - cpu_start < LIMIT * 1.25 and time.perf_counter() - began < 5:
        pass


def test_clock_counts_cpu_time_and_not_waiting():
    assert _measure(_burn_cpu) >= LIMIT
    assert _measure(lambda: time.sleep(LIMIT * 1.25)) < LIMIT


def test_wall_cap_fails_work_that_only_waits():
    with pytest.raises(AssertionError, match="ms wall"):
        assert_fast(lambda: time.sleep(0.06), 0.01, "sleep")
