#!/usr/bin/env python3
"""Characterization tests: pin the behaviour of the parser and loader functions refactored for S3776."""

import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO_ROOT, "hookify-plus"))

from core.config_loader import _get_plugin_rules, extract_frontmatter
from core.rule_engine import RuleEngine
from core.shell_parse import _BODIES, EXPANDED, GLOB, _options, _UnsureError, parse_commands, render

UNSURE = "UNSURE"


def _w(*words):
    return [w if isinstance(w, tuple) else (w, 0) for w in words]


class TestOptions:
    @pytest.mark.parametrize(
        ("words", "start", "short", "long", "kwargs", "expected"),
        [
            (_w("sudo", "ls"), 1, "u", ("user",), {}, (1, {})),
            (_w("sudo", "--", "-x"), 1, "u", ("user",), {}, (2, {})),
            (_w("sudo", "-u", "root", "ls"), 1, "u", ("user",), {}, (3, {"u": "root"})),
            (_w("sudo", "-uroot", "ls"), 1, "u", ("user",), {}, (2, {"u": "root"})),
            (_w("sudo", "-u"), 1, "u", ("user",), {}, (2, {})),
            (_w("sudo", "-Eu", "root", "ls"), 1, "u", ("user",), {}, (3, {"E": "", "u": "root"})),
            (_w("sudo", "-u", "-x", "ls"), 1, "u", ("user",), {}, (3, {"u": "-x"})),
            (_w("x", "-ab", "c"), 1, "", (), {"attached": "a"}, (2, {"a": "b"})),
            (_w("sudo", "--user=root", "ls"), 1, "u", ("user",), {}, (2, {"user": "root"})),
            (_w("sudo", "--user", "root", "ls"), 1, "u", ("user",), {}, (3, {"user": "root"})),
            (_w("sudo", "--user"), 1, "u", ("user",), {}, (2, {"user": ""})),
            (_w("sudo", "--login", "ls"), 1, "u", ("user",), {}, (2, {"login": ""})),
            (_w("su", "-", "root"), 1, "c", ("command",), {}, (1, {})),
            (_w("x", "+a", "y"), 1, "", (), {}, (1, {})),
            (_w("su", "root", "-c", "id"), 1, "c", ("command",), {"permute": True}, (4, {"c": "id"})),
            (_w("x", "", "y"), 1, "", (), {"permute": True}, (3, {})),
            (_w("sudo", ("$X", EXPANDED), "ls"), 1, "u", ("user",), {}, (1, {})),
            (_w("env", "-S", "a b", "c"), 1, "uS", ("split-string",), {"stop": frozenset("S")}, (3, {"S": "a b"})),
            (
                _w("env", "--split-string=a b", "c"),
                1,
                "uS",
                ("split-string",),
                {"stop": frozenset(["split-string"])},
                (2, {"split-string": "a b"}),
            ),
            (
                _w("env", "--split-string", "a b", "c"),
                1,
                "uS",
                ("split-string",),
                {"stop": frozenset(["split-string"])},
                (3, {"split-string": "a b"}),
            ),
            (_w("x", "-v", "-q", "y"), 1, "", (), {"stop": frozenset("v")}, (2, {"v": ""})),
            (_w("x", "-l", "-u", "r", "y"), 1, "u", ("user",), {"flags": ("l", ("login",))}, (4, {"l": "", "u": "r"})),
            (_w("x", "--login", "y"), 1, "u", ("user",), {"flags": ("l", ("login",))}, (2, {"login": ""})),
            (_w("x", "--zz=1", "y"), 1, "u", ("user",), {"flags": ("l", ("login",))}, (2, {"zz": "1"})),
            (_w("x", "-ab", "y"), 1, "", (), {"attached": "a", "flags": ("", ())}, (2, {"a": "b"})),
            (_w("x", "-lu", "r"), 1, "u", (), {"flags": ("l", ())}, (3, {"l": "", "u": "r"})),
            (_w("ssh", "-p", "22", "host", "cmd"), 3, "p", (), {}, (3, {})),
            (_w("su", ("$U", EXPANDED), "-c", "id"), 1, "c", ("command",), {"permute": True}, UNSURE),
            (_w("sudo", ("-$X", EXPANDED), "ls"), 1, "u", ("user",), {}, UNSURE),
            (_w("sudo", "-u", ("$U", EXPANDED), "ls"), 1, "u", ("user",), {}, UNSURE),
            (_w("sudo", ("-*", GLOB), "ls"), 1, "u", ("user",), {}, UNSURE),
            (_w("x", "-z", "y"), 1, "u", ("user",), {"flags": ("l", ("login",))}, UNSURE),
            (_w("x", "--zz", "y"), 1, "u", ("user",), {"flags": ("l", ("login",))}, UNSURE),
        ],
    )
    def test_options(self, words, start, short, long, kwargs, expected):  # noqa: PLR0913, PLR0917 - parametrized
        try:
            result = _options(words, start, short, long, **kwargs)
        except _UnsureError:
            result = UNSURE
        assert result == expected


def _render(command, cwd="", entries=None):
    _BODIES.clear()
    overflow = []
    lines = render(parse_commands(command), cwd, overflow, entries)
    return lines, overflow


class TestRender:
    @pytest.fixture
    def tree(self, tmp_path):
        for name in ("a.env", "b.env", "c.txt"):
            (tmp_path / name).write_text("")
        return str(tmp_path)

    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("cat *.env | grep x > o", ["cat a.env b.env | grep x > o", "grep x > o"]),
            (
                "bash -c 'sh -c \"cat *.env\" | wc' > f 2>&1 | tee g",
                [
                    "bash -c 'sh -c \"cat *.env\" | wc' > f 2>& 1 | tee g",
                    "sh -c 'cat *.env' | wc > f 2>& 1 | tee g",
                    "cat a.env b.env | wc > f 2>& 1 | tee g",
                    "wc > f 2>& 1 | tee g",
                    "tee g",
                ],
            ),
            ("a | b | c | d", ["a | b | c | d", "b | c | d", "c | d", "d"]),
            ("bash -c 'x; y' | z", ["bash -c 'x; y' | z", "x | z", "y | z", "z"]),
            (
                "sh <<<'cat <<<\"id\" | wc' > out",
                ["sh <<< 'cat <<<\"id\" | wc' > out", "cat <<< id | wc > out", "wc > out"],
            ),
            ("cat <<E\n$HOME\nE", ["cat << '$HOME\n'"]),
            ("cat <<'E'\n$HOME\nE", ["cat << E"]),
            (
                "echo id | bash 2>/dev/null | cat",
                ["echo id | bash 2> /dev/null | cat", "bash 2> /dev/null | cat", "cat", "id 2> /dev/null | cat"],
            ),
            ("(a | b) > o | c", ["a | b > o | c", "b > o | c", "c"]),
        ],
    )
    def test_lines(self, tree, command, expected):
        assert _render(command, tree) == (expected, [])

    def test_shared_entry_budget_overflows_later_words(self, tree):
        entries = [3]
        assert _render("ls *.env *.txt", tree, entries) == (["ls a.env b.env '*.txt'"], ["*.txt"])
        assert entries == [-1]

    def test_repeated_pattern_is_globbed_and_reported_once(self, tree):
        entries = [3]
        assert _render("ls *.txt *.env *.env", tree, entries) == (["ls c.txt '*.env' '*.env'"], ["*.env"])
        assert entries == [-1]

    def test_overflow_list_is_optional(self, tree):
        _BODIES.clear()
        assert render(parse_commands("ls *.env"), tree) == ["ls a.env b.env"]

    def test_output_budget_fails_closed(self):
        command = "bash -c '" + "x | " * 2000 + "y' | " + " | ".join(["z" * 50] * 60)
        assert parse_commands(command) is not None
        assert _render(command)[0] is None

    def test_nested_inheritance_is_shared_not_recomputed(self):
        command = 'bash -c \'bash -c "bash -c \\"echo ' + "a" * 3000 + ' | a | b\\" | c" | d\' | e'
        lines, _ = _render(command)
        assert [len(line) for line in lines] == [3057, 3045, 3035, 3025, 17, 13, 9, 5, 1]


class TestExtractFrontmatter:
    @pytest.mark.parametrize(
        ("content", "expected"),
        [
            ("name: x\n---\nbody", ({}, "name: x\n---\nbody")),
            ("---\nname: x\nbody", ({}, "---\nname: x\nbody")),
            (
                "---\nname: r\nenabled: TRUE\nmask_data: False\nmsg: 'it''s'\nq: \"a: b\"\n# comment\n\n---\n\nbody\n",
                ({"name": "r", "enabled": True, "mask_data": False, "msg": "it's", "q": "a: b"}, "body"),
            ),
            ("---\npattern: a---b\n---\nm", ({"pattern": "a---b"}, "m")),
            (
                "---\ntags:\n  - one\n  - 'two, three'\n  - \"four\"\nname: n\n---\n",
                ({"tags": ["one", "two, three", "four"], "name": "n"}, ""),
            ),
            (
                "---\nconditions:\n  - field: command, operator: regex_match, pattern: rm\n"
                "  - field: x, pattern: 'a, b'\n---\n",
                (
                    {
                        "conditions": [
                            {"field": "command", "operator": "regex_match", "pattern": "rm"},
                            {"field": "x", "pattern": "a"},
                        ]
                    },
                    "",
                ),
            ),
            (
                '---\nconditions:\n  - field: command\n    operator: contains\n    pattern: "a: b"\n'
                "  - field: file_path\n    pattern: x\nevent: bash\n---\nm",
                (
                    {
                        "conditions": [
                            {"field": "command", "operator": "contains", "pattern": "a: b"},
                            {"field": "file_path", "pattern": "x"},
                        ],
                        "event": "bash",
                    },
                    "m",
                ),
            ),
            (
                "---\nconditions:\n  - field: command\n    pattern: y\n---\n",
                ({"conditions": [{"field": "command", "pattern": "y"}]}, ""),
            ),
            ("---\nname: n\nconditions:\n---\n", ({"name": "n", "conditions": []}, "")),
            ("---\nconditions:\nname: n\n---\n", ({"conditions": [], "name": "n"}, "")),
            ("---\nconditions:\n  - field: a\n  pattern: shallow\n---\n", ({"conditions": [{"field": "a"}]}, "")),
            ("---\nname: n\n- stray\n---\n", ({"name": "n"}, "")),
            ("---\nname: n\n    k: v\n---\n", ({"name": "n"}, "")),
            (
                "---\nl:\n  - plain\n  - k: v\n    k2: v2\n  - k3: v3\n---\n",
                ({"l": ["plain", {"k": "v", "k2": "v2"}, {"k3": "v3"}]}, ""),
            ),
            ("---\r\nname: n\r\n---\r\nbody", ({"name": "n"}, "body")),
            ("---\npattern: https?://x\n---\n", ({"pattern": "https?://x"}, "")),
            ("---\nl:\n  - pattern: 'a, b'\n---\n", ({"l": [{"pattern": "a, b"}]}, "")),
            ("---\nl:\n\t- a\n---\n", ({"l": ["a"]}, "")),
            ("---\n:\n- a\nname: n\n- b\n---\n", ({"name": "n"}, "")),
            (
                "---\n:\n  - k: v\n    x: y\nname: n\nkk:\n  - z\n---\n",
                ({"name": "n", "kk": [{"k": "v", "x": "y"}, "z"]}, ""),
            ),
            ("---\n: v\n---\n", ({"": "v"}, "")),
        ],
    )
    def test_extract(self, content, expected):
        assert extract_frontmatter(content) == expected


class TestRawField:
    def raw(self, field, tool_name, tool_input, input_data=None):
        return RuleEngine()._raw_field(field, tool_name, tool_input, input_data)

    @pytest.mark.parametrize(
        ("field", "tool_name", "tool_input", "expected"),
        [
            ("command", "Bash", {"command": "ls"}, "ls"),
            ("timeout", "Bash", {"timeout": 5}, "5"),
            ("command", "Bash", {}, ""),
            ("new_text", "Bash", {}, None),
            ("content", "Write", {"content": "c"}, "c"),
            ("content", "Edit", {"new_string": "n"}, "n"),
            ("content", "Edit", {"content": "", "new_string": "n"}, ""),
            ("new_text", "Edit", {"new_string": "n"}, "n"),
            ("new_text", "Write", {"content": "c"}, "c"),
            ("new_text", "Write", {"new_string": "", "content": "c"}, "c"),
            ("new_string", "Write", {"new_string": "", "content": "c"}, ""),
            ("new_string", "Write", {"content": "c"}, "c"),
            ("old_text", "Edit", {"old_string": "o"}, "o"),
            ("old_string", "Write", {}, ""),
            ("file_path", "Write", {}, ""),
            ("command", "Write", {}, None),
            ("file_path", "NotebookEdit", {"notebook_path": "/n"}, "/n"),
            ("content", "NotebookEdit", {"new_source": "s"}, "s"),
            ("old_text", "NotebookEdit", {}, None),
            ("file_path", "Grep", {"path": "/p", "glob": "*.env*"}, "/p/*.env"),
            ("content", "Grep", {}, None),
            ("file_path", "Glob", {"path": "/g"}, "/g"),
            ("pattern", "Glob", {"pattern": "**"}, "**"),
            ("content", "Glob", {}, None),
            ("file_path", "Read", {}, None),
            ("anything", "", {}, None),
        ],
    )
    def test_tool_fields(self, field, tool_name, tool_input, expected):
        assert self.raw(field, tool_name, tool_input, {}) == expected

    @pytest.mark.parametrize(
        ("field", "input_data", "expected"),
        [
            ("reason", {"reason": "r"}, "r"),
            ("reason", {"x": 1}, ""),
            ("user_prompt", {"user_prompt": "p"}, "p"),
            ("user_prompt", {"x": 1}, ""),
            ("transcript", {"x": 1}, None),
            ("transcript", {"transcript_path": ""}, None),
        ],
    )
    def test_hook_fields(self, field, input_data, expected):
        assert self.raw(field, "", {}, input_data) == expected

    def test_hook_fields_need_input_data(self):
        assert self.raw("reason", "", {}, None) is None
        assert self.raw("reason", "", {}, {}) is None

    def test_tool_input_wins_over_hook_fields(self):
        assert self.raw("reason", "", {"reason": "tool"}, {"reason": "hook"}) == "tool"

    def test_tool_fields_still_read_with_hook_input(self):
        assert self.raw("command", "Bash", {}, {"cwd": "/"}) == ""
        assert self.raw("file_path", "Glob", {"path": "/g"}, {"reason": "r"}) == "/g"

    def test_hook_field_wins_over_tool_field(self):
        assert self.raw("user_prompt", "Bash", {}, {"user_prompt": "p"}) == "p"

    def test_transcript_is_read(self, tmp_path):
        path = tmp_path / "t.jsonl"
        path.write_text("log")
        assert self.raw("transcript", "", {}, {"transcript_path": str(path)}) == "log"

    def test_missing_transcript_is_empty(self, tmp_path, capsys):
        assert self.raw("transcript", "", {}, {"transcript_path": str(tmp_path / "none")}) == ""
        assert "not found" in capsys.readouterr().err

    def test_unreadable_transcript_is_empty(self, tmp_path, capsys):
        assert self.raw("transcript", "", {}, {"transcript_path": str(tmp_path)}) == ""
        assert "Error reading transcript" in capsys.readouterr().err

    def test_undecodable_transcript_is_empty(self, tmp_path, capsys, monkeypatch):
        def undecodable(*_args, **_kwargs):
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

        monkeypatch.setattr("builtins.open", undecodable)
        assert self.raw("transcript", "", {}, {"transcript_path": "/t.jsonl"}) == ""
        assert "Encoding error" in capsys.readouterr().err

    def test_permission_denied_transcript_is_empty(self, capsys, monkeypatch):
        def denied(*_args, **_kwargs):
            raise PermissionError(13, "denied")

        monkeypatch.setattr("builtins.open", denied)
        assert self.raw("transcript", "", {}, {"transcript_path": "/t.jsonl"}) == ""
        assert "Permission denied" in capsys.readouterr().err


class TestPluginRulesFaults:
    def test_unlistable_marketplace_is_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path / "missing" / "hookify-plus" / "2.0.0"))
        assert _get_plugin_rules() == []

    def test_sibling_without_rule_dir_is_skipped(self, tmp_path, monkeypatch):
        marketplace = tmp_path / "marketplace"
        (marketplace / "hookify-plus" / "2.0.0").mkdir(parents=True)
        (marketplace / "other" / "1.0.0" / ".in_use").mkdir(parents=True)
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(marketplace / "hookify-plus" / "2.0.0"))
        assert _get_plugin_rules() == []

    def test_unreadable_version_dir_warns_and_continues(self, tmp_path, monkeypatch, capsys):
        marketplace = tmp_path / "marketplace"
        (marketplace / "hookify-plus" / "2.0.0").mkdir(parents=True)
        for plugin in ("a-bad", "b-good"):
            rules = marketplace / plugin / "1.0.0" / "hookify-plus"
            rules.mkdir(parents=True)
            (rules / "r.md").write_text("---\nname: r\n---\n")
            (marketplace / plugin / "1.0.0" / ".in_use").mkdir()
        bad = str(marketplace / "a-bad" / "1.0.0" / "hookify-plus")
        real_glob = __import__("glob").glob

        def glob(pattern):
            if pattern.startswith(bad):
                raise OSError("denied")
            return real_glob(pattern)

        monkeypatch.setattr("core.config_loader.glob.glob", glob)
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(marketplace / "hookify-plus" / "2.0.0"))
        result = _get_plugin_rules()
        assert [os.path.basename(os.path.dirname(os.path.dirname(p))) for p in result] == ["1.0.0"]
        assert "b-good" in result[0]
        assert "Skipping" in capsys.readouterr().err
