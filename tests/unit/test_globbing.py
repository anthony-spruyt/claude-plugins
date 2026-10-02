#!/usr/bin/env python3
"""Unit tests for globbing: words bash makes of braces and globs."""

import os
import sys
import time

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO_ROOT, "hookify-plus"))

from core.globbing import MAX_ENTRIES, MAX_WORDS, expand
from core.rule_engine import normalise


@pytest.fixture
def tree(tmp_path, monkeypatch):
    for name in [".env", "README.md", "notes.md", "app/.env", "app/main.py", "a b.txt"]:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestGlobs:
    @pytest.mark.parametrize("pattern, expected", [
        (".e?v", [".env"]),
        (".en[v]", [".env"]),
        (".e[[:alpha:]]v", [".env"]),
        (".e[!x]v", [".env"]),
        ("*.md", ["README.md", "notes.md"]),
        ("*/.e?v", ["app/.env"]),
        ("a?b.txt", ["a b.txt"]),
        ("ap*/", ["app/"]),
    ])
    def test_matches(self, tree, pattern, expected):
        assert expand(pattern) == expected

    def test_star_skips_dot_files(self, tree):
        assert ".env" not in expand("*")

    def test_unmatched_glob_stays_literal(self, tree):
        assert expand("*.yaml") == ["*.yaml"]

    def test_escaped_glob_is_literal(self, tree):
        assert expand(".e\\?v") == [".e?v"]

    def test_absolute_path(self, tree):
        assert expand(str(tree) + "/.e?v") == [str(tree) + "/.env"]

    def test_relative_to_cwd(self, tree, monkeypatch):
        monkeypatch.chdir("/")
        assert expand("*/.e?v", cwd=str(tree)) == ["app/.env"]


class TestBraces:
    @pytest.mark.parametrize("pattern, expected", [
        (".{e,x}nv", [".env", ".xnv"]),
        ("{a,b{c,d}}", ["a", "bc", "bd"]),
        ("x{1..3}", ["x1", "x2", "x3"]),
        ("{a..c}", ["a", "b", "c"]),
        ("{5..1..2}", ["5", "3", "1"]),
        ("{e..e}", ["e"]),
    ])
    def test_expands(self, pattern, expected):
        assert expand(pattern) == expected

    @pytest.mark.parametrize("pattern", ["{a}", "{}", "{a..}", "{1..a}", "\\{a,b}"])
    def test_not_a_brace_expansion(self, pattern):
        assert expand(pattern) == [pattern.replace("\\", "")]

    def test_braces_then_glob(self, tree):
        assert expand("{.e?v,*.py}") == [".env", "*.py"]


class TestLimits:
    def test_too_many_words(self):
        assert expand("{1..%d}" % (MAX_WORDS * 2)) is None

    def test_nested_braces_multiply(self):
        assert expand("{a,b}" * 12) is None

    def test_entry_budget_shared(self, tree):
        budget = [3]
        assert expand("*", budget) is None
        assert budget[0] < 0

    def test_big_directory_gives_up_fast(self, tmp_path):
        for n in range(MAX_ENTRIES + 10):
            (tmp_path / str(n)).touch()
        start = time.perf_counter()
        assert expand("*/*/*", cwd=str(tmp_path)) is None
        assert time.perf_counter() - start < 0.2

    def test_many_globs_share_one_budget(self, tmp_path):
        for n in range(MAX_ENTRIES // 4):
            (tmp_path / str(n)).touch()
        lines = normalise("cat " + " ".join("?%d*" % n for n in range(10)), str(tmp_path))
        assert lines is None
