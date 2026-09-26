#!/usr/bin/env python3
"""Configuration loader for hookify plugin.

Loads and parses hookify-plus/*.md rule files.
"""

from __future__ import annotations  # Python 3.8 compatibility (PEP 563)

import os
import sys
import glob
import re
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field


@dataclass
class Condition:
    """A single condition for matching."""
    field: str  # "command", "new_text", "old_text", "file_path", etc.
    operator: str  # "regex_match", "contains", "equals", etc.
    pattern: str

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Condition':
        """Create Condition from dict."""
        pattern = data.get('pattern') or data.get('value', '')
        return cls(
            field=data.get('field', ''),
            operator=data.get('operator', 'regex_match'),
            pattern=pattern
        )


@dataclass
class Rule:
    """A hookify rule."""
    name: str
    enabled: bool
    event: str  # "bash", "file", "stop", "all", etc.
    pattern: Optional[str] = None  # Simple pattern (legacy)
    conditions: List[Condition] = field(default_factory=list)
    action: str = "warn"  # "warn" or "block"
    tool_matcher: Optional[str] = None
    message: str = ""
    warn_once: bool = False
    warn_interval: int = 0  # Warn every N matches (0 = every time)

    @classmethod
    def from_dict(cls, frontmatter: Dict[str, Any], message: str) -> 'Rule':
        """Create Rule from frontmatter dict and message body."""
        conditions = []

        if 'conditions' in frontmatter:
            cond_list = frontmatter['conditions']
            if isinstance(cond_list, list):
                conditions = [Condition.from_dict(c) for c in cond_list]

        simple_pattern = frontmatter.get('pattern')
        if simple_pattern and not conditions:
            event = frontmatter.get('event', 'all')
            if event == 'bash':
                field = 'command'
            elif event == 'file':
                field = 'new_text'
            elif event == 'read':
                field = 'file_path'
            else:
                field = 'content'

            conditions = [Condition(
                field=field,
                operator='regex_match',
                pattern=simple_pattern
            )]

        warn_interval = frontmatter.get('warn_interval', 0)
        if isinstance(warn_interval, str):
            try:
                warn_interval = int(warn_interval)
            except ValueError:
                warn_interval = 0

        return cls(
            name=frontmatter.get('name', 'unnamed'),
            enabled=frontmatter.get('enabled', True),
            event=frontmatter.get('event', 'all'),
            pattern=simple_pattern,
            conditions=conditions,
            action=frontmatter.get('action', 'warn'),
            tool_matcher=frontmatter.get('tool_matcher'),
            message=message.strip(),
            warn_once=frontmatter.get('warn_once', False),
            warn_interval=warn_interval
        )


def extract_frontmatter(content: str) -> tuple[Dict[str, Any], str]:
    """Extract YAML frontmatter and message body from markdown.

    Returns (frontmatter_dict, message_body).

    Supports multi-line dictionary items in lists by preserving indentation.
    """
    if not content.startswith('---'):
        return {}, content

    parts = content.split('---', 2)
    if len(parts) < 3:
        return {}, content

    frontmatter_text = parts[1]
    message = parts[2].strip()

    frontmatter = {}
    lines = frontmatter_text.split('\n')

    current_key = None
    current_list = []
    current_dict = {}
    in_list = False
    in_dict_item = False

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue

        indent = len(line) - len(line.lstrip())

        if indent == 0 and ':' in line and not line.strip().startswith('-'):
            if in_list and current_key:
                if in_dict_item and current_dict:
                    current_list.append(current_dict)
                    current_dict = {}
                frontmatter[current_key] = current_list
                in_list = False
                in_dict_item = False
                current_list = []

            key, value = line.split(':', 1)
            key = key.strip()
            value = value.strip()

            if not value:
                current_key = key
                in_list = True
                current_list = []
            else:
                value = value.strip('"').strip("'")
                if value.lower() == 'true':
                    value = True
                elif value.lower() == 'false':
                    value = False
                frontmatter[key] = value

        elif stripped.startswith('-') and in_list:
            if in_dict_item and current_dict:
                current_list.append(current_dict)
                current_dict = {}

            item_text = stripped[1:].strip()

            if ':' in item_text and ',' in item_text:
                item_dict = {}
                for part in item_text.split(','):
                    if ':' in part:
                        k, v = part.split(':', 1)
                        item_dict[k.strip()] = v.strip().strip('"').strip("'")
                current_list.append(item_dict)
                in_dict_item = False
            elif ':' in item_text:
                in_dict_item = True
                k, v = item_text.split(':', 1)
                current_dict = {k.strip(): v.strip().strip('"').strip("'")}
            else:
                current_list.append(item_text.strip('"').strip("'"))
                in_dict_item = False

        elif indent > 2 and in_dict_item and ':' in line:
            k, v = stripped.split(':', 1)
            current_dict[k.strip()] = v.strip().strip('"').strip("'")

    if in_list and current_key:
        if in_dict_item and current_dict:
            current_list.append(current_dict)
        frontmatter[current_key] = current_list

    return frontmatter, message


RULE_DIR_NAME = "hookify-plus"
RULE_GLOB = "*.md"


def _get_project_rules() -> List[str]:
    """Find rules in .claude/hookify-plus/ relative to cwd."""
    project_dir = os.path.join(".claude", RULE_DIR_NAME)
    if not os.path.isdir(project_dir):
        return []
    return glob.glob(os.path.join(project_dir, RULE_GLOB))


def _get_global_rules() -> List[str]:
    """Find rules in ~/.claude/hookify-plus/."""
    home = os.path.expanduser("~")
    global_dir = os.path.join(home, ".claude", RULE_DIR_NAME)
    if not os.path.isdir(global_dir):
        return []
    return glob.glob(os.path.join(global_dir, RULE_GLOB))


IN_USE_DIR = ".in_use"


def _active_version_dirs(plugin_path: str) -> List[str]:
    """Return version dirs under a plugin that have an .in_use marker."""
    try:
        entries = os.listdir(plugin_path)
    except OSError:
        return []

    active_dirs = []
    for entry in entries:
        full = os.path.join(plugin_path, entry)
        if not os.path.isdir(full):
            continue
        if os.path.isdir(os.path.join(full, IN_USE_DIR)):
            active_dirs.append(full)

    return active_dirs


def _get_plugin_rules() -> List[str]:
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
    self_plugin_name = os.path.basename(plugin_dir)
    rule_files = []

    try:
        for sibling in os.listdir(marketplace_dir):
            if sibling == self_plugin_name:
                continue
            sibling_path = os.path.join(marketplace_dir, sibling)
            if not os.path.isdir(sibling_path) or os.path.islink(sibling_path):
                continue
            for version_dir in _active_version_dirs(sibling_path):
                try:
                    hookify_dir = os.path.join(version_dir, RULE_DIR_NAME)
                    if os.path.isdir(hookify_dir):
                        rule_files.extend(glob.glob(os.path.join(hookify_dir, RULE_GLOB)))
                except OSError as e:
                    print(f"Warning: Skipping {version_dir}: {e}", file=sys.stderr)
                    continue
    except OSError:
        pass

    return rule_files


def discover_rule_files() -> List[str]:
    """Discover all rule files from project, global, and plugin sources."""
    return _get_project_rules() + _get_global_rules() + _get_plugin_rules()


def load_rules(event: Optional[str] = None) -> List[Rule]:
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
            if event:
                if rule.event != 'all' and rule.event != event:
                    continue
            if rule.enabled:
                rules.append(rule)
        except (IOError, OSError, PermissionError) as e:
            print(f"Warning: Failed to read {file_path}: {e}", file=sys.stderr)
            continue
        except (ValueError, KeyError, AttributeError, TypeError) as e:
            print(f"Warning: Failed to parse {file_path}: {e}", file=sys.stderr)
            continue
        except Exception as e:
            print(f"Warning: Unexpected error loading {file_path} ({type(e).__name__}): {e}", file=sys.stderr)
            continue

    return rules


def load_rule_file(file_path: str) -> Optional[Rule]:
    """Load a single rule file.

    Returns:
        Rule object or None if file is invalid.
    """
    try:
        with open(file_path, 'r') as f:
            content = f.read()

        frontmatter, message = extract_frontmatter(content)

        if not frontmatter:
            print(f"Warning: {file_path} missing YAML frontmatter (must start with ---)", file=sys.stderr)
            return None

        rule = Rule.from_dict(frontmatter, message)
        return rule

    except (IOError, OSError, PermissionError) as e:
        print(f"Error: Cannot read {file_path}: {e}", file=sys.stderr)
        return None
    except (ValueError, KeyError, AttributeError, TypeError) as e:
        print(f"Error: Malformed rule file {file_path}: {e}", file=sys.stderr)
        return None
    except UnicodeDecodeError as e:
        print(f"Error: Invalid encoding in {file_path}: {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Error: Unexpected error parsing {file_path} ({type(e).__name__}): {e}", file=sys.stderr)
        return None


if __name__ == '__main__':
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
