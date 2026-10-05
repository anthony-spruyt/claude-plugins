#!/usr/bin/env python3
"""Replay tool calls from Claude Code session logs through the hookify rules.

Shows, per rule, what it matches today, where that differs from what fired when
the session ran, and secret-looking calls that no block rule caught.
"""

import argparse
import glob
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO_ROOT, "hookify-plus"))

from core.config_loader import load_rule_file
from core.rule_engine import RuleEngine
from core.tools import event_for_tool

MAX_SHOWN = 400
MAX_EXAMPLES = 25
MAX_SUSPECTS = 300

RULE_NAME = re.compile(r"\*\*\[([a-z0-9][a-z0-9-]*)\]\*\*")

SUSPECT = re.compile(
    r"\.env\b|\.ssh\b|id_(?:rsa|ed25519|ecdsa)|\.aws\b|\.kube/config|\.docker/config|\.npmrc|\.pypirc|"
    r"\.netrc|\.git-credentials|credentials|secret|token|passw|private.?key|\bsops\b|\bage\b|"
    r"\bgpg\b|decrypt|\bprintenv\b|(?<![\w./-])env(?![\w./-])|/proc/\S*environ|\bdeclare -p\b|\bset\b\s*(?:\||$)",
    re.IGNORECASE | re.MULTILINE,
)
SUSPECT_FIELDS = ("command", "file_path", "notebook_path", "path", "glob", "pattern")

SECRET_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)", re.DOTALL),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_\w{20,}|sk-[A-Za-z0-9_-]{20,}|"
               r"AKIA[0-9A-Z]{16}|xox[abposr]-[A-Za-z0-9-]{10,}|AGE-SECRET-KEY-1\w+|glpat-[\w-]{20,}|"
               r"AIza[\w-]{30,}|[sr]k_(?:live|test)_\w{16,}|npm_\w{30,}|eyJ[\w-]{5,}\.[\w-]{5,}\.[\w-]{5,})"),
    re.compile(r"(?<![\w/+=.-])(?=[\w/+]{0,39}[A-Z])(?=[\w/+]{0,39}[a-z])(?=[\w/+]{0,39}[0-9])"
               r"[A-Za-z0-9/+]{40}(?![\w/+=.-])"),
]
KEEP_PREFIX = [
    re.compile(r"(?i)(\bAuthorization\s*:\s*(?:\w+\s+)?)(?![$<])[^\s'\"]+"),
    re.compile(r"(?i)(\b(?:Bearer|Basic)\s+)(?![$<])(?=[\w.~+/=-]*(?-i:[A-Z0-9+/=]))[\w.~+/=-]{8,}"),
    re.compile(r"(://[^/@\s:]+:)[^@\s/]+(?=@)"),
    re.compile(r"(?i)(\b(?:x-)?(?:api-?key|auth-token)\s*:\s*)(?![$<])[^\s'\"]+"),
    re.compile(r"(?i)(--?(?:password|passwd|token|secret|api-?key)[= ]['\"]?)(?![$<])[^\s'\"]+"),
    re.compile(r"(\bmysql\w*\b[^\n|;&]*?\s-p)(?![$<\s])\S+"),
    re.compile(r"(?i)(\"[^\"\n]*(?:token|secret|passw|api_?key|private_?key|credential)[^\"\n]*\"\s*:\s*\")"
               r"(?:\\.|[^\"\\])+"),
]
# Bounded runs keep this linear on long keyword-heavy text; PASS/PAT only match as whole name segments
SECRET_NAME = (
    r"\b(?:\w{0,32}?(?:TOKEN|SECRET|PASSW(?:OR)?D|PASSPHRASE|API_?KEY|PRIVATE_?KEY|CREDENTIALS?)"
    r"|(?:\w{1,32}_)?(?:PG)?PASS|\w{1,32}_PAT)(?:_\w{1,32})?(?<!_FILE)(?<!_PATH)(?<!_DIR)"
)
SECRET_ASSIGNMENT = re.compile(
    r"(?i)(" + SECRET_NAME + r"\s*[=:]\s*)"
    r"('(?!\$)[^'\n]*'|\"(?!\$)[^\"\n]*\"|(?![$'\"])[^\s'\";&|]+)"
)


def _mask_value(m: re.Match) -> str:
    value = m.group(2)
    quote = value[0] if value[:1] in ("'", '"') else ""
    return f"{m.group(1)}{quote}<redacted>{quote}"


def redact(text: str) -> str:
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("<redacted>", text)
    for pattern in KEEP_PREFIX:
        text = pattern.sub(lambda m: m.group(1) + "<redacted>", text)
    return SECRET_ASSIGNMENT.sub(_mask_value, text)


def find_transcripts(root: str, include=None, exclude=None) -> list:
    """List logs under root, filtered by substrings of the top-level project folder name."""
    found = []
    for path in sorted(glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True)):
        project = os.path.relpath(path, root).split(os.sep)[0]
        if include and not any(s in project for s in include):
            continue
        if exclude and any(s in project for s in exclude):
            continue
        found.append(path)
    return found


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(_text(c.get("text", c.get("content", ""))) if isinstance(c, dict) else str(c)
                         for c in content)
    return ""


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def parse_transcript(path: str):
    """Return (tool calls, {tool_use_id: rule names that fired})."""
    calls = []
    fired = defaultdict(set)
    blocked = set()
    timed_out = set()
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(entry, dict):
                continue
            kind = entry.get("type")
            content = _dict(entry.get("message")).get("content")
            if kind == "assistant" and isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tool_id = block.get("id")
                        calls.append({"id": tool_id if isinstance(tool_id, str) else None, "tool": block.get("name"),
                                      "input": _dict(block.get("input")), "cwd": entry.get("cwd", ""),
                                      "source": path})
            elif kind == "user" and isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        text = _text(block.get("content"))
                        names = RULE_NAME.findall(text) if text.lstrip().startswith("PreToolUse:") else []
                        tool_id = block.get("tool_use_id")
                        if names and isinstance(tool_id, str):
                            fired[tool_id].update(names)
                            blocked.add(tool_id)
            elif kind == "attachment":
                attachment = _dict(entry.get("attachment"))
                hook_type = str(attachment.get("type") or "")
                tool_id = attachment.get("toolUseID")
                if not hook_type.startswith("hook_") or not isinstance(tool_id, str) or not tool_id:
                    continue
                if hook_type == "hook_cancelled" and attachment.get("timedOut") \
                        and attachment.get("hookEvent") == "PreToolUse" \
                        and "pretooluse.py" in str(attachment.get("command", "")):
                    timed_out.add(tool_id)
                names = RULE_NAME.findall(json.dumps(attachment.get("blockingError", "")))
                if names:
                    fired[tool_id].update(names)
    for call in calls:
        call["blocked"] = call["id"] in blocked
        call["timed_out"] = call["id"] in timed_out
    return calls, dict(fired)


def load_rule_dir(*dirs: str) -> list:
    rules = []
    for rules_dir in dirs:
        for path in sorted(glob.glob(os.path.join(rules_dir, "*.md"))):
            rule = load_rule_file(path)
            if rule and rule.enabled:
                rules.append(rule)
    return rules


def repo_rule_dirs() -> list:
    dirs = sorted(glob.glob(os.path.join(REPO_ROOT, "*", "hookify-plus"))) + [os.path.join(REPO_ROOT, ".claude", "hookify-plus")]
    return [d for d in dirs if glob.glob(os.path.join(d, "*.md"))]


def resolve_rule_dirs(extra=None) -> list:
    return repo_rule_dirs() + list(extra or [])


def matching_rules(call: dict, rules: list) -> set:
    event = event_for_tool(call["tool"])
    if not event:
        return set()
    engine = RuleEngine()
    input_data = {"hook_event_name": "PreToolUse", "tool_name": call["tool"],
                  "tool_input": call["input"], "cwd": call.get("cwd", "")}
    return {r.name for r in rules
            if r.event in (event, "all") and engine._rule_matches(r, input_data)}


def _shown(call: dict) -> str:
    tool_input = call["input"]
    if "command" in tool_input:
        text = str(tool_input["command"])
    elif call["tool"] in ("Edit", "Write", "NotebookEdit"):
        body = tool_input.get("new_string") or tool_input.get("content") or tool_input.get("new_source") or ""
        text = f"{tool_input.get('file_path') or tool_input.get('notebook_path')}\n{body}"
    else:
        text = json.dumps(tool_input, sort_keys=True)
    text = redact(text)
    return text if len(text) <= MAX_SHOWN else text[:MAX_SHOWN] + " …[truncated]"


def is_suspect(call: dict, matched_blocks: set) -> bool:
    """Secret-looking call that no block rule matched."""
    if matched_blocks or call["tool"] not in ("Bash", "PowerShell", "Monitor", "Read", "Grep", "Glob"):
        return False
    text = "\n".join(str(call["input"][f]) for f in SUSPECT_FIELDS if call["input"].get(f))
    return bool(SUSPECT.search(text))


def _example(call: dict, bucket: dict, cap: int = MAX_EXAMPLES) -> None:
    key = (call["tool"], _shown(call))
    if key in bucket:
        bucket[key]["count"] += 1
    elif len(bucket) < cap:
        bucket[key] = {"tool": call["tool"], "command": key[1], "count": 1,
                       "source": os.path.basename(call["source"])}


def build_report(paths: list, rules: list) -> dict:
    names = {r.name for r in rules}
    block_names = {r.name for r in rules if r.action == "block"}
    per_rule = {name: {"hits": 0, "examples": {}, "started": {}, "stopped": {}} for name in names}
    suspects = {}
    suspect_keys = set()
    timeouts = {}
    calls_seen = 0
    for path in paths:
        calls, fired = parse_transcript(path)
        for call in calls:
            calls_seen += 1
            matched = matching_rules(call, rules)
            then = fired.get(call["id"], set()) & names
            # PostToolUse never runs on a call PreToolUse blocked, so warn drift there is noise
            drifting = names if not call.get("blocked") else block_names
            for name in matched:
                per_rule[name]["hits"] += 1
                _example(call, per_rule[name]["examples"])
            for name in (matched - then) & drifting:
                _example(call, per_rule[name]["started"])
            for name in (then - matched) & drifting:
                _example(call, per_rule[name]["stopped"])
            if is_suspect(call, matched & block_names):
                suspect_keys.add((call["tool"], _shown(call)))
                _example(call, suspects, MAX_SUSPECTS)
            if call.get("timed_out"):
                _example(call, timeouts)
    for stats in per_rule.values():
        for bucket in ("examples", "started", "stopped"):
            stats[bucket] = list(stats[bucket].values())
    return {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "transcripts": len(paths), "calls": calls_seen,
            "rules": dict(sorted(per_rule.items())), "suspects": list(suspects.values()),
            "suspects_total": len(suspect_keys), "timeouts": list(timeouts.values())}


def _block(examples: list) -> str:
    return "\n".join(f"- `{e['tool']}` ×{e['count']} ({e['source']})\n\n  ```\n  "
                     + e["command"].replace("\n", "\n  ") + "\n  ```" for e in examples)


def render_markdown(report: dict) -> str:
    out = [f"# Hookify replay — {report['generated']}", "",
           f"{report['transcripts']} transcripts, {report['calls']} tool calls.", "",
           "| Rule | Hits | Started | Stopped |", "| --- | ---: | ---: | ---: |"]
    for name, stats in report["rules"].items():
        out.append(f"| {name} | {stats['hits']} | {len(stats['started'])} | {len(stats['stopped'])} |")
    for name, stats in report["rules"].items():
        if not stats["hits"] and not stats["stopped"]:
            continue
        out += ["", f"## {name}", "", "### Matches now", "", _block(stats["examples"]) or "_none_"]
        if stats["started"]:
            out += ["", "### Matches now, did not fire in the log", "", _block(stats["started"])]
        if stats["stopped"]:
            out += ["", "### Fired in the log, does not match now", "", _block(stats["stopped"])]
    out += ["", "## PreToolUse timeouts (no block rule ran)", "", _block(report["timeouts"]) or "_none_"]
    shown = len(report["suspects"])
    out += ["", f"## Suspects (secret-looking, no block rule matched): {shown} of {report['suspects_total']}", "",
            _block(report["suspects"]) or "_none_"]
    return "\n".join(out) + "\n"


def _write_private(path: str, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)


def write_report(report: dict, out: str) -> None:
    if not os.path.isdir(out):
        os.makedirs(out)
        os.chmod(out, 0o700)
    _write_private(os.path.join(out, "report.json"), json.dumps(report, indent=1))
    _write_private(os.path.join(out, "report.md"), render_markdown(report))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--projects", default=os.path.expanduser("~/.claude/projects"),
                        help="Folder holding Claude Code session logs")
    parser.add_argument("--rules", action="append", default=None,
                        help="Extra rule folder to load on top of this repo's (repeatable)")
    parser.add_argument("--project", action="append", help="Only project folders containing this text (repeatable)")
    parser.add_argument("--exclude-project", action="append", help="Skip project folders containing this text (repeatable)")
    parser.add_argument("--since", help="Only logs modified on or after this date (YYYY-MM-DD)")
    parser.add_argument("--out", default="/tmp/hookify-replay", help="Where to write report.md and report.json")
    args = parser.parse_args()

    rule_dirs = resolve_rule_dirs(args.rules)
    paths = find_transcripts(args.projects, args.project, args.exclude_project)
    if args.since:
        cutoff = datetime.strptime(args.since, "%Y-%m-%d").timestamp()
        paths = [p for p in paths if os.path.getmtime(p) >= cutoff]

    report = build_report(paths, load_rule_dir(*rule_dirs))
    write_report(report, args.out)

    print(f"{report['transcripts']} transcripts, {report['calls']} tool calls")
    for name, stats in report["rules"].items():
        print(f"  {name:40} hits={stats['hits']:<5} started={len(stats['started']):<3} stopped={len(stats['stopped'])}")
    print(f"  timeouts={len(report['timeouts'])}")
    print(f"  suspects={report['suspects_total']} (report shows {len(report['suspects'])})")
    print(f"Report: {os.path.join(args.out, 'report.md')}")


if __name__ == "__main__":
    main()
