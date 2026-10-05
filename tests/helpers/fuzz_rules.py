#!/usr/bin/env python3
"""Fuzz the hookify rules and shell parser.

speed   Long repeated random commands; flags any rule slower than the limit.
crash   Mutated test and log commands; flags any input that crashes the parser.
bypass  Random commands run for real in a sandbox; flags ones that leak a canary
        secret while no block rule fires.
"""

import argparse
import glob
import os
import random
import re
import subprocess
import sys
import tempfile
import time
import traceback
from collections import Counter

import yaml

HELPERS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HELPERS)

import replay_transcripts as rt
from core.rule_engine import RuleEngine, clean_lines
from core.shell_parse import normalise

MAX_COMMAND = 20000
CANARY = "c4n4ry-l34k-v4lu3"

E = "e" + "nv"
SPEED_ATOMS = [
    "echo ", "printf ", "$(", ")", "`", '"', "'", "\\", "${A", "}", "$TOKEN", "$X", " ", "\n",
    ";", "&&", "||", "|", "<<A", "<<<", ">", ">>", "2>&1", "git commit -m ", "gh pr create --body ",
    "-m ", "-d ", "--", "sudo ", "bash -c ", "eval ", E + " ", "set ", "export ", "declare -p ",
    "cat ", ".np" + "mrc", "/proc/self/", "environ", "secrets.yaml", "10.0.0" + ".1 ", "192.168.",
    "X=", "a", "-S ", "-u ", "{", "(", "[[", "if ", "then ", "do ", "find . -exec ", "\\;",
    "gpg ", "sops ", "openssl enc ", "age ", "sed -i ", "perl -pi ", "$env:", "Get-ChildItem ",
]
CRASH_INSERTS = list(" \t\n;&|()<>'\"\\$`{}[]*?!#=-0xuU%") + [
    "$(", "${", "$'", "<<", "\\x0", "\\u", "\\U110000", "\\ud800", "-c ", "-S ", "eval ", "bash -c ",
]
BYPASS_HEADS = [
    "", "echo ", "bash -c ", "sh -c ", "eval ", "timeout 5 ", "nohup ", "xargs ", "find . -maxdepth 0 -exec ",
    "git commit -m ", "git commit -F - ", "gh pr create --title x --body ", "gh pr create --body-file - ",
    "git tag v1 -m ", "gh release create v1 --notes ", "gh pr comment 1 -b ",
]
BYPASS_PIECES = [
    "'", '"', " ", "\n", ";", "&&", "||", "|", E, "printenv", "set", "export -p", "declare -p", "cat .env",
    "$SECRET_TOKEN", "${SECRET_TOKEN}", "${!S*}", "<<'A'", '<<"A"', "A", "$(cat <<'X'\n", "X", ")", "\\",
    "x", "-m", " -m ", "\t", "cd /", '"$(cat <<\'X\'\n', "A)", "X)", "\nA\n", "\nX\n)\"", f"'{E}'",
    f'"{E}"', f" {E}", f"\n{E}\n", "#", "=", "{}", "\\;", "$(", "`", "sort", "grep T",
]
STUBS = "git(){ :; }; gh(){ :; }; set +H\n"
DUMPED = re.compile(r"SECRET_TOKEN=[\"']?" + CANARY)


def load_corpus(logs_root=None) -> list:
    """Commands from every YAML suite, plus Bash commands from session logs when given."""
    seen = {}
    for path in sorted(glob.glob(os.path.join(rt.REPO_ROOT, "tests", "hooks", "*.yaml"))):
        with open(path, encoding="utf-8") as f:
            for case in (yaml.safe_load(f) or {}).get("test_cases", []):
                if case.get("command"):
                    seen.setdefault(case["command"], None)
    if logs_root:
        for path in rt.find_transcripts(logs_root):
            calls, _ = rt.parse_transcript(path)
            for call in calls:
                command = call["input"].get("command")
                if call["tool"] == "Bash" and isinstance(command, str) and command:
                    seen.setdefault(command, None)
    return list(seen)


def mutate(command: str, rng: random.Random, corpus: list) -> str:
    for _ in range(rng.randint(1, 4)):
        roll, at = rng.random(), rng.randint(0, len(command))
        if roll < .5:
            command = command[:at] + rng.choice(CRASH_INSERTS) + command[at:]
        elif roll < .8:
            command = command[:at] + command[at + 1:]
        else:
            other = rng.choice(corpus)
            start = rng.randint(0, len(other))
            command = command[:at] + other[start:start + 20] + command[at:]
    return command


def repeat_unit(unit: str, length: int = MAX_COMMAND) -> str:
    return (unit * (length // max(1, len(unit)) + 1))[:length]


def slow_rules(rules: list, command: str, limit: float) -> list:
    engine = RuleEngine()
    data = {"tool_name": "Bash", "tool_input": {"command": command}}
    slow = []
    for rule in rules:
        clean_lines.cache_clear()
        start = time.perf_counter()
        engine._rule_matches(rule, data)
        elapsed = time.perf_counter() - start
        if elapsed > limit:
            slow.append((elapsed, rule.name))
    return slow


def crash_key(command: str):
    try:
        normalise(command)
    except Exception as e:
        return type(e).__name__, traceback.extract_tb(e.__traceback__)[-1].lineno
    return None


def bypass_kind(command: str, rules: list, workdir: str):
    """How the command leaks the canary secret with no block rule matching, or None.

    dump: name=value pairs (env dumps, .env reads). print: the bare value on stdout.
    error: the value only shows up in stderr, e.g. run as a command name.
    """
    with open(os.path.join(workdir, ".env"), "w", encoding="utf-8") as f:
        f.write(f"SECRET_TOKEN={CANARY}\n")
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": workdir, "SECRET_TOKEN": CANARY}
    try:
        out = subprocess.run(["bash", "-c", STUBS + command], env=env, cwd=workdir, capture_output=True,
                             text=True, timeout=5, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return None
    if CANARY not in out.stdout + out.stderr:
        return None
    blockers = [r for r in rules if r.action == "block"]
    if rt.matching_rules({"tool": "Bash", "input": {"command": command}, "cwd": workdir}, blockers):
        return None
    if DUMPED.search(out.stdout + out.stderr):
        return "dump"
    return "print" if CANARY in out.stdout else "error"


def run_speed(rules, rng, seconds, limit) -> int:
    worst = {}
    trials = 0
    deadline = time.time() + seconds
    while time.time() < deadline:
        trials += 1
        unit = "".join(rng.choice(SPEED_ATOMS) for _ in range(rng.randint(1, 6)))
        for elapsed, name in slow_rules(rules, repeat_unit(unit), limit):
            if elapsed > worst.get(name, (0,))[0]:
                worst[name] = (elapsed, unit)
    print(f"{trials} trials, limit {limit}s")
    for name, (elapsed, unit) in sorted(worst.items(), key=lambda kv: -kv[1][0]):
        print(f"SLOW {elapsed:.2f}s {name} unit={unit!r}")
    return 1 if worst else 0


def run_crash(corpus, rng, count) -> int:
    crashes = Counter()
    smallest = {}
    for command in corpus:
        key = crash_key(command)
        if key:
            crashes[key] += 1
            smallest.setdefault(key, command)
    for _ in range(count):
        command = mutate(rng.choice(corpus), rng, corpus)
        key = crash_key(command)
        if key:
            crashes[key] += 1
            if key not in smallest or len(command) < len(smallest[key]):
                smallest[key] = command
    print(f"{count} mutations over {len(corpus)} seed commands")
    for key, n in crashes.most_common():
        print(f"CRASH {key[0]} at shell_parse line {key[1]} x{n}: {smallest[key]!r}")
    return 1 if crashes else 0


def run_bypass(rules, rng, count) -> int:
    found = {}
    with tempfile.TemporaryDirectory(prefix="hookify-bypass-") as workdir:
        for _ in range(count):
            command = rng.choice(BYPASS_HEADS) + "".join(rng.choice(BYPASS_PIECES)
                                                         for _ in range(rng.randint(1, 8)))
            kind = bypass_kind(command, rules, workdir)
            if kind:
                found.setdefault(kind, set()).add(command)
    print(f"{count} commands run, {sum(map(len, found.values()))} distinct bypasses")
    for kind in ("dump", "print", "error"):
        for command in sorted(found.get(kind, ()), key=len):
            print(f"BYPASS {kind} {command!r}")
    return 1 if found else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=["speed", "crash", "bypass"])
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--seconds", type=float, default=240, help="speed: how long to run")
    parser.add_argument("--limit", type=float, default=0.2, help="speed: slowest allowed seconds per rule")
    parser.add_argument("--count", type=int, help="crash/bypass: how many inputs (default 200000 / 1500)")
    parser.add_argument("--from-logs", nargs="?", const=os.path.expanduser("~/.claude/projects"),
                        help="crash: also seed from Bash commands in session logs")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    rules = rt.load_rule_dir(*rt.repo_rule_dirs())
    if args.mode == "speed":
        sys.exit(run_speed(rules, rng, args.seconds, args.limit))
    if args.mode == "crash":
        sys.exit(run_crash(load_corpus(args.from_logs), rng, args.count or 200000))
    sys.exit(run_bypass(rules, rng, args.count or 1500))


if __name__ == "__main__":
    main()
