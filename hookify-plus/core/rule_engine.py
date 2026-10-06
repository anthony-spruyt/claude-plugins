#!/usr/bin/env python3
"""Rule evaluation engine for hookify plugin."""

import os
import posixpath
import re
import sys
from functools import lru_cache
from typing import Any, Dict, List, Optional

from core.config_loader import Condition, Rule
from core.globbing import MAX_ENTRIES
from core.masking import mask_data
from core.opaque import opaque
from core.shell_parse import _BODIES, parse_commands, render


@lru_cache(maxsize=128)
def compile_regex(pattern: str) -> re.Pattern:
    """Compile regex pattern with caching.

    Args:
        pattern: Regex pattern string

    Returns:
        Compiled regex pattern
    """
    return re.compile(pattern, re.IGNORECASE | re.DOTALL)


def normalise(command: str, cwd: str = "", entries: Optional[List[int]] = None):
    functions, overflow = set(), []
    _BODIES.clear()
    commands = parse_commands(command, functions)
    if commands is None:
        return None
    lines = render(commands, cwd, overflow, entries)
    return None if lines is None else (lines, opaque(command, commands, functions), overflow)


def _clean_path(path: str) -> str:
    clean = posixpath.normpath(path)
    return clean + "/" if path.endswith("/") and clean != "/" else clean


@lru_cache(maxsize=16)
def clean_lines(command: str, cwd: str = "") -> Optional[tuple]:
    """Cached parse: (clean lines, opaque) or None. Several rules parse the same command."""
    try:
        parsed = normalise(command, cwd)
    except Exception:  # noqa: BLE001
        return None
    return None if parsed is None else (tuple(parsed[0]), parsed[1], tuple(parsed[2]))


SEGMENT_BREAKS = frozenset(";&|\n()`")
LEADING_KEYWORDS = re.compile(r"^(?:\s*(?:if|then|else|elif|do|while|until|!|\{|\}|fi|done|esac|time)(?=\s|$))+")


def _segments(command: str) -> List[str]:
    """Split on unquoted separators and parens, dropping leading keywords."""
    out, start, i, quote = [], 0, 0, ""
    while i < len(command):
        c = command[i]
        if c == "\\" and quote != "'":
            i += 2
            continue
        if quote:
            quote = "" if c == quote else quote
        elif c in "'\"":
            quote = c
        elif c in SEGMENT_BREAKS:
            out.append(command[start:i])
            start = i + 1
        i += 1
    out.append(command[start:])
    return [s for s in (LEADING_KEYWORDS.sub("", s).strip() for s in out) if s]


@lru_cache(maxsize=16)
def segment_lines(command: str, cwd: str = "") -> tuple:
    """(clean lines, glob overflow) of each piece of a command that parses on its own."""
    lines, overflow, entries = [], [], [MAX_ENTRIES]
    for segment in _segments(command):
        try:
            parsed = normalise(segment, cwd, entries)
        except Exception:  # noqa: BLE001
            continue
        if parsed is not None:
            lines.extend(parsed[0])
            overflow.extend(parsed[2])
    return tuple(lines), tuple(overflow)


def _read_transcript(input_data: Dict[str, Any]) -> Optional[str]:
    """The transcript text, "" when it can't be read, or None without a transcript_path."""
    transcript_path = input_data.get("transcript_path")
    if not transcript_path:
        return None
    try:
        with open(transcript_path) as f:
            return f.read()
    except FileNotFoundError:
        print(f"Warning: Transcript file not found: {transcript_path}", file=sys.stderr)
    except PermissionError:
        print(f"Warning: Permission denied reading transcript: {transcript_path}", file=sys.stderr)
    except OSError as e:
        print(f"Warning: Error reading transcript {transcript_path}: {e}", file=sys.stderr)
    except UnicodeDecodeError as e:
        print(f"Warning: Encoding error in transcript {transcript_path}: {e}", file=sys.stderr)
    return ""


def _grep_target(tool_input: Dict[str, Any]) -> str:
    path = tool_input.get("path", "")
    # Trailing wildcards stripped so `.env*` meets the rules' `$`-anchored patterns
    name = tool_input.get("glob", "").rstrip("*?.")
    if not name:
        return path
    return path.rstrip("/\\") + "/" + name


def _key(name: str):
    return lambda tool_input: tool_input.get(name, "")


def _first(primary: str, fallback: str):
    # `or`, not a default: an empty primary still falls back
    return lambda tool_input: tool_input.get(primary) or tool_input.get(fallback, "")


HOOK_FIELDS = {
    "reason": lambda input_data: input_data.get("reason", ""),
    "transcript": _read_transcript,
    "user_prompt": lambda input_data: input_data.get("user_prompt", ""),
}

_FILE_TOOL_FIELDS = {
    # Write sends `content`, Edit sends `new_string`
    "content": _first("content", "new_string"),
    "new_text": _first("new_string", "content"),
    "new_string": _first("new_string", "content"),
    "old_text": _key("old_string"),
    "old_string": _key("old_string"),
    "file_path": _key("file_path"),
}

TOOL_FIELDS = {
    "Bash": {"command": _key("command")},
    "Write": _FILE_TOOL_FIELDS,
    "Edit": _FILE_TOOL_FIELDS,
    "NotebookEdit": {
        "file_path": _key("notebook_path"),
        "new_text": _key("new_source"),
        "new_string": _key("new_source"),
        "content": _key("new_source"),
    },
    "Grep": {"file_path": _grep_target},
    "Glob": {"file_path": _key("path")},
}


STRING_OPERATORS = {
    "contains": lambda value, pattern: pattern in value,
    "not_contains": lambda value, pattern: pattern not in value,
    "equals": lambda value, pattern: value == pattern,
    "starts_with": lambda value, pattern: value.startswith(pattern),
    "ends_with": lambda value, pattern: value.endswith(pattern),
}


class RuleEngine:
    """Evaluates rules against hook input data."""

    def __init__(self):
        """Initialize rule engine."""

    def evaluate_rules(self, rules: List[Rule], input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluate all rules and return combined results.

        Checks all rules and accumulates matches. Blocking rules take priority
        over warning rules. All matching rule messages are combined.

        Args:
            rules: List of Rule objects to evaluate
            input_data: Hook input JSON (tool_name, tool_input, etc.)

        Returns:
            Response dict with systemMessage, hookSpecificOutput, etc.
            Empty dict {} if no rules match.
        """
        hook_event = input_data.get("hook_event_name", "")
        blocking_rules = []
        warning_rules = []

        for rule in rules:
            if self._rule_matches(rule, input_data):
                if rule.action == "block":
                    blocking_rules.append(rule)
                else:
                    warning_rules.append(rule)

        if blocking_rules:
            messages = [f"**[{r.name}]**\n{r.message}" for r in blocking_rules]
            combined_message = "\n\n".join(messages)

            if hook_event == "Stop":
                return {"decision": "block", "reason": combined_message, "systemMessage": combined_message}
            if hook_event in ["PreToolUse", "PostToolUse"]:
                return {
                    "hookSpecificOutput": {
                        "hookEventName": hook_event,
                        "permissionDecision": "deny",
                        "permissionDecisionReason": combined_message,  # So Claude sees WHY blocked
                    },
                    "systemMessage": combined_message,
                }
            return {"systemMessage": combined_message}

        if warning_rules:
            messages = [f"**[{r.name}]**\n{r.message}" for r in warning_rules]
            return {"systemMessage": "\n\n".join(messages)}

        return {}

    def _rule_matches(self, rule: Rule, input_data: Dict[str, Any]) -> bool:
        """Check if rule matches input data.

        Args:
            rule: Rule to evaluate
            input_data: Hook input data

        Returns:
            True if rule matches, False otherwise
        """
        tool_name = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input", {})

        if rule.tool_matcher and not self._matches_tool(rule.tool_matcher, tool_name):
            return False

        if not rule.conditions:
            return False

        for condition in rule.conditions:
            if not self._check_condition(
                condition, tool_name, tool_input, input_data, mask=rule.mask_data, strict=rule.action == "block"
            ):
                return False

        return True

    def _matches_tool(self, matcher: str, tool_name: str) -> bool:
        """Check if tool_name matches the matcher pattern.

        Args:
            matcher: Pattern like "Bash", "Edit|Write", "*"
            tool_name: Actual tool name

        Returns:
            True if matches
        """
        if matcher == "*":
            return True

        patterns = matcher.split("|")
        return tool_name in patterns

    def _check_condition(
        self,
        condition: Condition,
        tool_name: str,
        tool_input: Dict[str, Any],
        input_data: Optional[Dict[str, Any]] = None,
        mask: bool = False,
        strict: bool = True,
    ) -> bool:
        """Check if a single condition matches.

        Args:
            condition: Condition to check
            tool_name: Tool being used
            tool_input: Tool input dict
            input_data: Full hook input data (for Stop events, etc.)
            mask: Blank non-executing text in the command before matching
            strict: Also try the fallback when the command runs code the parser can't see

        Returns:
            True if condition matches
        """
        field_value = self._extract_field(condition.field, tool_name, tool_input, input_data)
        if field_value is None:
            return False
        raw_value = field_value
        if mask and tool_name == "Bash" and condition.field == "command":
            field_value = mask_data(field_value)

        if condition.operator == "glob_overflow":
            return (
                tool_name == "Bash"
                and condition.field == "command"
                and self._glob_overflow(raw_value, (input_data or {}).get("cwd") or os.getcwd())
            )
        if condition.operator == "command_match":
            cwd = (input_data or {}).get("cwd") or os.getcwd()
            return self._command_match(condition, tool_name, raw_value, field_value, mask, strict, cwd)
        if condition.operator == "regex_match":
            return self._regex_match(condition.pattern, field_value)
        if condition.operator == "not_regex_match":
            return not self._regex_match(condition.pattern, field_value)
        test = STRING_OPERATORS.get(condition.operator)
        return test is not None and test(field_value, condition.pattern)

    def _command_match(
        self,
        condition: Condition,
        tool_name: str,
        raw_value: str,
        field_value: str,
        mask: bool,
        strict: bool,
        cwd: str = "",
    ) -> bool:
        pattern = condition.pattern
        if condition.field != "command":
            return self._regex_match(pattern, raw_value)
        if tool_name != "Bash":
            return self._regex_match(condition.fallback or pattern, field_value)
        parsed = clean_lines(raw_value, cwd)
        if parsed is None or (strict and parsed[1] and condition.fallback):
            if self._regex_match(condition.fallback or pattern, field_value):
                return True
            if parsed is None:
                # Block rules also try each piece that parses, so one unreadable piece can't hide the rest
                lines = segment_lines(field_value, cwd)[0] if strict else ()
                return any(self._regex_match(pattern, line) for line in lines)
        lines = parsed[0]
        if mask:
            lines = [mask_data(line) for line in lines]
        return any(self._regex_match(pattern, line) for line in lines)

    @staticmethod
    def _glob_overflow(command: str, cwd: str) -> bool:
        parsed = clean_lines(command, cwd)
        return bool(parsed[2] if parsed is not None else segment_lines(command, cwd)[1])

    def _extract_field(
        self, field: str, tool_name: str, tool_input: Dict[str, Any], input_data: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        value = self._raw_field(field, tool_name, tool_input, input_data)
        if field == "file_path" and value:
            return _clean_path(value)
        return value

    def _raw_field(
        self, field: str, tool_name: str, tool_input: Dict[str, Any], input_data: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """Extract field value from tool input or hook input data.

        Args:
            field: Field name like "command", "new_text", "file_path", "reason", "transcript"
            tool_name: Tool being used (may be empty for Stop events)
            tool_input: Tool input dict
            input_data: Full hook input (for accessing transcript_path, reason, etc.)

        Returns:
            Field value as string, or None if not found
        """
        if field in tool_input:
            value = tool_input[field]
            return value if isinstance(value, str) else str(value)

        if input_data and field in HOOK_FIELDS:
            value = HOOK_FIELDS[field](input_data)
            if value is not None:
                return value

        extract = TOOL_FIELDS.get(tool_name, {}).get(field)
        return None if extract is None else extract(tool_input)

    def _regex_match(self, pattern: str, text: str) -> bool:
        """Check if pattern matches text using regex.

        Args:
            pattern: Regex pattern
            text: Text to match against

        Returns:
            True if pattern matches
        """
        try:
            regex = compile_regex(pattern)
            return bool(regex.search(text))

        except re.error as e:
            print(f"Invalid regex pattern '{pattern}': {e}", file=sys.stderr)
            return False


if __name__ == "__main__":
    from core.config_loader import Condition, Rule

    rule = Rule(
        name="test-rm",
        enabled=True,
        event="bash",
        conditions=[Condition(field="command", operator="regex_match", pattern=r"rm\s+-rf")],
        message="Dangerous rm command!",
    )

    engine = RuleEngine()

    test_input = {"tool_name": "Bash", "tool_input": {"command": "rm -rf /tmp/test"}}

    result = engine.evaluate_rules([rule], test_input)
    print("Match result:", result)

    test_input2 = {"tool_name": "Bash", "tool_input": {"command": "ls -la"}}

    result2 = engine.evaluate_rules([rule], test_input2)
    print("Non-match result:", result2)
