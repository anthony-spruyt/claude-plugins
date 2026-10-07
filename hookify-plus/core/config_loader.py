#!/usr/bin/env python3
"""Configuration loader for hookify plugin.

Loads and parses hookify-plus/*.md rule files.
"""

from __future__ import annotations  # Python 3.8 compatibility (PEP 563)

import glob
import json
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Condition:
    """A single condition for matching."""

    field: str  # "command", "new_text", "old_text", "file_path", etc.
    operator: str  # "regex_match", "contains", "equals", etc.
    pattern: str
    fallback: str | None = None  # command_match: regex for commands the shell parser can't read

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Condition:
        """Create Condition from dict."""
        pattern = data.get("pattern") or data.get("value", "")
        return cls(
            field=data.get("field", ""),
            operator=data.get("operator", "regex_match"),
            pattern=pattern,
            fallback=data.get("fallback") or None,
        )


@dataclass
class Rule:
    """A hookify rule."""

    name: str
    enabled: bool
    event: str  # "bash", "file", "stop", "all", etc.
    pattern: str | None = None  # Simple pattern (legacy)
    conditions: list[Condition] = field(default_factory=list)
    action: str = "warn"  # "warn" or "block"
    tool_matcher: str | None = None
    message: str = ""
    warn_once: bool = False
    warn_interval: int = 0  # Warn every N matches (0 = every time)
    mask_data: bool = False

    @classmethod
    def from_dict(cls, frontmatter: dict[str, Any], message: str) -> Rule:
        """Create Rule from frontmatter dict and message body."""
        conditions = []

        if "conditions" in frontmatter:
            cond_list = frontmatter["conditions"]
            if isinstance(cond_list, list):
                conditions = [Condition.from_dict(c) for c in cond_list]

        simple_pattern = frontmatter.get("pattern")
        if simple_pattern and not conditions:
            event = frontmatter.get("event", "all")
            if event == "bash":
                field = "command"
            elif event == "file":
                field = "new_text"
            elif event == "read":
                field = "file_path"
            else:
                field = "content"

            conditions = [Condition(field=field, operator="regex_match", pattern=simple_pattern)]

        warn_interval = frontmatter.get("warn_interval", 0)
        if isinstance(warn_interval, str):
            try:
                warn_interval = int(warn_interval)
            except ValueError:
                warn_interval = 0

        return cls(
            name=frontmatter.get("name", "unnamed"),
            enabled=frontmatter.get("enabled", True),
            event=frontmatter.get("event", "all"),
            pattern=simple_pattern,
            conditions=conditions,
            action=frontmatter.get("action", "warn"),
            tool_matcher=frontmatter.get("tool_matcher"),
            message=message.strip(),
            warn_once=frontmatter.get("warn_once", False),
            warn_interval=warn_interval,
            mask_data=frontmatter.get("mask_data", False) is True,
        )


_QUOTED = re.compile(r"""'(?:[^']|'')*'|"(?:[^"\\]|\\.)*\"""", re.DOTALL)


def _unquote(value: str) -> str:
    """Remove one pair of YAML quotes; '' inside single quotes is a literal '."""
    value = value.strip()
    if _QUOTED.fullmatch(value):
        inner = value[1:-1]
        return inner.replace("''", "'") if value[0] == "'" else inner
    return value.strip('"').strip("'")


def extract_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Extract YAML frontmatter and message body from markdown.

    Returns (frontmatter_dict, message_body).

    Supports multi-line dictionary items in lists by preserving indentation.
    """
    if not content.startswith("---"):
        return {}, content

    # Close only on a line starting with ---, so patterns may contain ---.
    end = content.find("\n---", 3)
    if end < 0:
        return {}, content

    parser = _FrontmatterParser()
    for line in content[3:end].split("\n"):
        parser.feed(line)
    return parser.finish(), content[end + 4 :].strip()


def _scalar(value: str) -> str | bool:
    value = _unquote(value)
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    return value


def _inline_dict(item_text: str) -> dict[str, str] | None:
    """`k: v, k2: v2` as a dict, or None when the item isn't one (a lone quoted value may hold commas)."""
    if ":" not in item_text or "," not in item_text or _QUOTED.fullmatch(item_text.split(":", 1)[1].strip()):
        return None
    pairs = (part.split(":", 1) for part in item_text.split(",") if ":" in part)
    return {k.strip(): _unquote(v) for k, v in pairs}


LIST_ITEM_INDENT = 2


class _FrontmatterParser:
    """Line-at-a-time parser for the frontmatter subset rules use: scalars, and lists of scalars or dicts."""

    def __init__(self):
        self.frontmatter: dict[str, Any] = {}
        self.key: str | None = None
        self.items: list[Any] = []
        self.item: dict[str, str] = {}
        self.in_list = False
        self.in_item = False

    def feed(self, line: str) -> None:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            return
        indent = len(line) - len(line.lstrip())
        if indent == 0 and ":" in line and not stripped.startswith("-"):
            self._top_level_key(line)
        elif stripped.startswith("-") and self.in_list:
            self._list_item(stripped[1:].strip())
        elif indent > LIST_ITEM_INDENT and self.in_item and ":" in line:
            k, v = stripped.split(":", 1)
            self.item[k.strip()] = _unquote(v)

    def finish(self) -> dict[str, Any]:
        if self.in_list and self.key:
            self._close_item()
            self.frontmatter[self.key] = self.items
        return self.frontmatter

    def _top_level_key(self, line: str) -> None:
        if self.in_list and self.key:
            self._close_item()
            self.frontmatter[self.key] = self.items
            self.in_list = self.in_item = False
            self.items = []
        key, value = (part.strip() for part in line.split(":", 1))
        if value:
            self.frontmatter[key] = _scalar(value)
        else:
            self.key, self.in_list, self.items = key, True, []

    def _list_item(self, item_text: str) -> None:
        self._close_item()
        inline = _inline_dict(item_text)
        if inline is not None:
            self.items.append(inline)
            self.in_item = False
        elif ":" in item_text:
            k, v = item_text.split(":", 1)
            self.item, self.in_item = {k.strip(): _unquote(v)}, True
        else:
            self.items.append(_unquote(item_text))
            self.in_item = False

    def _close_item(self) -> None:
        if self.in_item and self.item:
            self.items.append(self.item)
            self.item = {}


RULE_DIR_NAME = "hookify-plus"
RULE_GLOB = "*.md"


def _get_project_rules() -> list[str]:
    """Find rules in .claude/hookify-plus/ relative to cwd."""
    project_dir = os.path.join(".claude", RULE_DIR_NAME)
    if not os.path.isdir(project_dir):
        return []
    return glob.glob(os.path.join(project_dir, RULE_GLOB))


def _get_global_rules() -> list[str]:
    """Find rules in ~/.claude/hookify-plus/."""
    home = os.path.expanduser("~")
    global_dir = os.path.join(home, ".claude", RULE_DIR_NAME)
    if not os.path.isdir(global_dir):
        return []
    return glob.glob(os.path.join(global_dir, RULE_GLOB))


IN_USE_DIR = ".in_use"


def _read_proc_stat(pid: int) -> list[str] | None:
    """Return /proc/<pid>/stat fields after comm, or None if unavailable."""
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as f:
            return f.read().rsplit(")", 1)[1].split()
    except (OSError, IndexError):
        return None


def _session_holders() -> dict[int, str]:
    """Map each ancestor pid of this hook to its process start time."""
    holders = {}
    pid = os.getpid()
    while pid > 1 and pid not in holders:
        fields = _read_proc_stat(pid)
        if not fields:
            break
        holders[pid] = fields[19]
        pid = int(fields[1])
    return holders


def _held_by(version_dir: str, holders: dict[int, str]) -> bool:
    """True if a marker in version_dir belongs to a live ancestor of this hook."""
    marker_dir = os.path.join(version_dir, IN_USE_DIR)
    try:
        names = os.listdir(marker_dir)
    except OSError:
        return False
    for name in names:
        try:
            with open(os.path.join(marker_dir, name), encoding="utf-8") as f:
                marker = json.load(f)
            pid = int(marker["pid"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if holders.get(pid) == str(marker.get("procStart")):
            return True
    return False


def _active_version_dirs(plugin_path: str, holders: dict[int, str] | None = None) -> list[str]:
    """Return version dirs under a plugin that are in use.

    With holders, only dirs held by this session count. Claude Code leaves
    .in_use markers from other and dead sessions, so a bare marker dir is not
    enough to tell an old version from the current one.
    """
    try:
        entries = os.listdir(plugin_path)
    except OSError:
        return []

    active_dirs = []
    for entry in entries:
        full = os.path.join(plugin_path, entry)
        if not os.path.isdir(full):
            continue
        if not os.path.isdir(os.path.join(full, IN_USE_DIR)):
            continue
        if holders is None or _held_by(full, holders):
            active_dirs.append(full)

    return active_dirs


def _get_plugin_rules() -> list[str]:
    """Find rules in sibling plugin hookify-plus/ directories.

    Cache layout: cache/{marketplace}/{plugin}/{version}/
    CLAUDE_PLUGIN_ROOT points to the version dir, so we go up two levels
    to reach the marketplace dir where sibling plugins live.
    Only scans version dirs with .in_use markers to avoid loading stale rules.
    """
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if not plugin_root:
        return []

    plugin_dir = os.path.dirname(plugin_root)
    marketplace_dir = os.path.dirname(plugin_dir)

    holders = _session_holders()
    if not _held_by(plugin_root, holders):
        holders = None

    rule_files = []
    try:
        for sibling_path in _sibling_plugins(marketplace_dir, os.path.basename(plugin_dir)):
            for version_dir in _active_version_dirs(sibling_path, holders):
                rule_files.extend(_version_rules(version_dir))
    except OSError:
        pass

    return rule_files


def _sibling_plugins(marketplace_dir: str, self_plugin_name: str) -> list[str]:
    """Real (non-symlink) plugin dirs beside this one; symlinks could point outside the marketplace."""
    siblings = []
    for sibling in os.listdir(marketplace_dir):
        sibling_path = os.path.join(marketplace_dir, sibling)
        if sibling != self_plugin_name and os.path.isdir(sibling_path) and not os.path.islink(sibling_path):
            siblings.append(sibling_path)
    return siblings


def _version_rules(version_dir: str) -> list[str]:
    try:
        hookify_dir = os.path.join(version_dir, RULE_DIR_NAME)
        if os.path.isdir(hookify_dir):
            return glob.glob(os.path.join(hookify_dir, RULE_GLOB))
    except OSError as e:
        print(f"Warning: Skipping {version_dir}: {e}", file=sys.stderr)
    return []


def discover_rule_files() -> list[str]:
    """Discover all rule files from project, global, and plugin sources."""
    return _get_project_rules() + _get_global_rules() + _get_plugin_rules()


def load_rules(event: str | None = None) -> list[Rule]:
    """Load all hookify rules from discovered locations.

    Scans:
    - .claude/hookify-plus/*.md (project-level, relative to cwd)
    - ~/.claude/hookify-plus/*.md (user's home directory)
    - <sibling_plugin>/hookify-plus/*.md (same marketplace)

    Args:
        event: Optional event filter ("bash", "file", "stop", etc.)

    Returns:
        List of enabled Rule objects matching the event.
    """
    rules = []
    files = discover_rule_files()

    for file_path in files:
        try:
            rule = load_rule_file(file_path)
            if not rule:
                continue
            if event and rule.event not in ("all", event):
                continue
            if rule.enabled:
                rules.append(rule)
        except OSError as e:
            print(f"Warning: Failed to read {file_path}: {e}", file=sys.stderr)
            continue
        except (ValueError, KeyError, AttributeError, TypeError) as e:
            print(f"Warning: Failed to parse {file_path}: {e}", file=sys.stderr)
            continue
        except Exception as e:  # noqa: BLE001
            print(f"Warning: Unexpected error loading {file_path} ({type(e).__name__}): {e}", file=sys.stderr)
            continue

    return rules


def load_rule_file(file_path: str) -> Rule | None:
    """Load a single rule file.

    Returns:
        Rule object or None if file is invalid.
    """
    try:
        with open(file_path) as f:
            content = f.read()

        frontmatter, message = extract_frontmatter(content)

        if not frontmatter:
            print(f"Warning: {file_path} missing YAML frontmatter (must start with ---)", file=sys.stderr)
            return None

        return Rule.from_dict(frontmatter, message)

    except OSError as e:
        print(f"Error: Cannot read {file_path}: {e}", file=sys.stderr)
        return None
    except (ValueError, KeyError, AttributeError, TypeError) as e:
        print(f"Error: Malformed rule file {file_path}: {e}", file=sys.stderr)
        return None
    except UnicodeDecodeError as e:
        print(f"Error: Invalid encoding in {file_path}: {e}", file=sys.stderr)
        return None
    except Exception as e:  # noqa: BLE001
        print(f"Error: Unexpected error parsing {file_path} ({type(e).__name__}): {e}", file=sys.stderr)
        return None


if __name__ == "__main__":
    import sys

    test_content = """---
name: test-rule
enabled: true
event: bash
pattern: "rm -rf"
---

⚠️ Dangerous command detected!
"""

    fm, msg = extract_frontmatter(test_content)
    print("Frontmatter:", fm)
    print("Message:", msg)

    rule = Rule.from_dict(fm, msg)
    print("Rule:", rule)
