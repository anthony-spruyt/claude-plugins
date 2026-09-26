#!/usr/bin/env python3
"""Unit tests for tool-to-event mapping and per-tool field extraction."""

import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO_ROOT, "hookify-plus"))

from core.config_loader import Rule
from core.rule_engine import RuleEngine
from core.tools import event_for_tool


class TestEventForTool:
    @pytest.mark.parametrize("tool_name", ["Bash", "PowerShell", "Monitor"])
    def test_shell_tools_map_to_bash(self, tool_name):
        assert event_for_tool(tool_name) == "bash"

    @pytest.mark.parametrize("tool_name", ["Edit", "Write", "NotebookEdit"])
    def test_file_tools_map_to_file(self, tool_name):
        assert event_for_tool(tool_name) == "file"

    @pytest.mark.parametrize("tool_name", ["Read", "Glob", "Grep"])
    def test_read_tools_map_to_read(self, tool_name):
        assert event_for_tool(tool_name) == "read"

    @pytest.mark.parametrize("tool_name", ["Update", "LS", "MultiEdit", "WebFetch", ""])
    def test_unknown_tools_have_no_event(self, tool_name):
        assert event_for_tool(tool_name) is None


class TestFieldExtraction:
    def extract(self, field, tool_name, tool_input):
        return RuleEngine()._extract_field(field, tool_name, tool_input, {})

    def test_notebook_edit_file_path_is_notebook_path(self):
        assert self.extract("file_path", "NotebookEdit", {"notebook_path": "/p/.env"}) == "/p/.env"

    def test_notebook_edit_new_text_is_new_source(self):
        assert self.extract("new_text", "NotebookEdit", {"new_source": "API_KEY=1"}) == "API_KEY=1"

    @pytest.mark.parametrize("field", ["new_text", "new_string", "content"])
    def test_notebook_edit_new_content_fields_are_new_source(self, field):
        assert self.extract(field, "NotebookEdit", {"new_source": "API_KEY=1"}) == "API_KEY=1"

    def test_grep_file_path_is_path(self):
        assert self.extract("file_path", "Grep", {"pattern": "x", "path": "/home/u/.ssh/id_rsa"}) == "/home/u/.ssh/id_rsa"

    def test_grep_file_path_joins_glob_filter(self):
        assert self.extract("file_path", "Grep", {"pattern": "x", "path": "/home/u", "glob": "id_rsa"}) == "/home/u/id_rsa"

    def test_grep_glob_without_path(self):
        assert self.extract("file_path", "Grep", {"pattern": "x", "glob": ".env"}) == "/.env"

    @pytest.mark.parametrize("filter_, expected", [
        (".env*", "/project/.env"),
        (".env.*", "/project/.env"),
        (".*", "/project"),
        ("id_rsa?*", "/project/id_rsa"),
        ("*", "/project"),
        ("**", "/project"),
    ])
    def test_trailing_wildcards_are_stripped(self, filter_, expected):
        assert self.extract("file_path", "Grep", {"pattern": "x", "path": "/project", "glob": filter_}) == expected

    def test_glob_lists_names_so_only_path_counts(self):
        assert self.extract("file_path", "Glob", {"pattern": "**/.env", "path": "/project"}) == "/project"

    def test_grep_trailing_slash_on_path(self):
        assert self.extract("file_path", "Grep", {"pattern": "x", "path": "/project/", "glob": "*.ts"}) == "/project/*.ts"


class TestNotebookEditNewString:
    def test_new_string_rule_matches_notebook_edit(self):
        rule = Rule.from_dict({
            "name": "r",
            "event": "file",
            "action": "block",
            "conditions": [{"field": "new_string", "operator": "contains", "pattern": "API_KEY"}],
        }, "blocked")
        result = RuleEngine().evaluate_rules([rule], {
            "hook_event_name": "PreToolUse",
            "tool_name": "NotebookEdit",
            "tool_input": {"notebook_path": "/p/n.ipynb", "new_source": "API_KEY=1"},
        })
        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"


class TestSimplePatternField:
    def test_read_event_pattern_matches_file_path(self):
        rule = Rule.from_dict({"name": "r", "event": "read", "pattern": "id_rsa"}, "")
        assert rule.conditions[0].field == "file_path"
