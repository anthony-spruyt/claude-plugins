#!/usr/bin/env python3
"""Unit tests for config_loader discovery logic."""

import os
import sys
import tempfile
import pytest

# Add hookify-plus to path
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO_ROOT, "hookify-plus"))

from core.config_loader import _get_project_rules, _get_global_rules, _get_plugin_rules, _active_version_dirs, discover_rule_files


class TestProjectRules:
    def test_finds_rules_in_claude_hookify_plus_dir(self, tmp_path, monkeypatch):
        """Rules in .claude/hookify-plus/*.md are discovered."""
        monkeypatch.chdir(tmp_path)
        rule_dir = tmp_path / ".claude" / "hookify-plus"
        rule_dir.mkdir(parents=True)
        (rule_dir / "block-test.md").write_text("---\nname: test\n---\ntest")
        (rule_dir / "not-a-rule.txt").write_text("ignored")

        result = _get_project_rules()
        assert len(result) == 1
        assert "block-test.md" in result[0]

    def test_returns_empty_when_no_dir(self, tmp_path, monkeypatch):
        """Returns empty list when .claude/hookify-plus/ doesn't exist."""
        monkeypatch.chdir(tmp_path)
        result = _get_project_rules()
        assert result == []


class TestGlobalRules:
    def test_finds_rules_in_home_claude_hookify_plus(self, tmp_path, monkeypatch):
        """Rules in ~/.claude/hookify-plus/*.md are discovered."""
        monkeypatch.setenv("HOME", str(tmp_path))
        rule_dir = tmp_path / ".claude" / "hookify-plus"
        rule_dir.mkdir(parents=True)
        (rule_dir / "global-rule.md").write_text("---\nname: global\n---\nglobal")

        result = _get_global_rules()
        assert len(result) == 1
        assert "global-rule.md" in result[0]

    def test_returns_empty_when_no_global_dir(self, tmp_path, monkeypatch):
        """Returns empty list when ~/.claude/hookify-plus/ doesn't exist."""
        monkeypatch.setenv("HOME", str(tmp_path))
        result = _get_global_rules()
        assert result == []


class TestPluginRules:
    def test_discovers_sibling_plugin_rules(self, tmp_path, monkeypatch):
        """Rules in sibling plugin hookify-plus/ dirs are discovered.

        Cache layout: {marketplace}/{plugin}/{version}/
        """
        marketplace = tmp_path / "marketplace"
        (marketplace / "hookify-plus" / "2.0.0").mkdir(parents=True)
        sibling_rules = marketplace / "security-hooks" / "1.0.0" / "hookify-plus"
        sibling_rules.mkdir(parents=True)
        (sibling_rules / "block-test.md").write_text("---\nname: test\n---\ntest")

        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(marketplace / "hookify-plus" / "2.0.0"))
        result = _get_plugin_rules()
        assert len(result) == 1
        assert "block-test.md" in result[0]

    def test_skips_self_but_finds_siblings(self, tmp_path, monkeypatch):
        """Skips own plugin dir but still discovers sibling rules."""
        marketplace = tmp_path / "marketplace"
        self_version = marketplace / "hookify-plus" / "2.0.0"
        self_version.mkdir(parents=True)
        (self_version / "hookify-plus").mkdir()
        (self_version / "hookify-plus" / "own-rule.md").write_text("---\nname: own\n---\n")

        sibling_rules = marketplace / "security-hooks" / "1.0.0" / "hookify-plus"
        sibling_rules.mkdir(parents=True)
        (sibling_rules / "sibling-rule.md").write_text("---\nname: sibling\n---\n")

        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(self_version))
        result = _get_plugin_rules()
        assert len(result) == 1
        assert "sibling-rule.md" in result[0]

    def test_returns_empty_without_env_var(self, monkeypatch):
        """Returns empty when CLAUDE_PLUGIN_ROOT is not set."""
        monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
        result = _get_plugin_rules()
        assert result == []

    def test_multiple_siblings(self, tmp_path, monkeypatch):
        """Discovers rules from multiple sibling plugins."""
        marketplace = tmp_path / "marketplace"
        (marketplace / "hookify-plus" / "2.0.0").mkdir(parents=True)

        for plugin in ["security-hooks", "best-practices"]:
            rules_dir = marketplace / plugin / "1.0.0" / "hookify-plus"
            rules_dir.mkdir(parents=True)
            (rules_dir / f"{plugin}-rule.md").write_text(f"---\nname: {plugin}\n---\n")

        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(marketplace / "hookify-plus" / "2.0.0"))
        result = _get_plugin_rules()
        assert len(result) == 2

    def test_prefers_in_use_versions(self, tmp_path, monkeypatch):
        """Only scans version dirs with .in_use marker when present."""
        marketplace = tmp_path / "marketplace"
        (marketplace / "hookify-plus" / "2.0.0").mkdir(parents=True)

        # Old version without .in_use — should be skipped
        old_rules = marketplace / "security-hooks" / "0.9.0" / "hookify-plus"
        old_rules.mkdir(parents=True)
        (old_rules / "old-rule.md").write_text("---\nname: old\n---\n")

        # Current version with .in_use — should be scanned
        new_rules = marketplace / "security-hooks" / "1.0.0" / "hookify-plus"
        new_rules.mkdir(parents=True)
        (new_rules / "new-rule.md").write_text("---\nname: new\n---\n")
        (marketplace / "security-hooks" / "1.0.0" / ".in_use").mkdir()

        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(marketplace / "hookify-plus" / "2.0.0"))
        result = _get_plugin_rules()
        assert len(result) == 1
        assert "new-rule.md" in result[0]

    def test_falls_back_to_all_versions_without_in_use(self, tmp_path, monkeypatch):
        """Scans all version dirs when no .in_use markers exist."""
        marketplace = tmp_path / "marketplace"
        (marketplace / "hookify-plus" / "2.0.0").mkdir(parents=True)

        for ver in ["0.9.0", "1.0.0"]:
            rules_dir = marketplace / "security-hooks" / ver / "hookify-plus"
            rules_dir.mkdir(parents=True)
            (rules_dir / f"rule-{ver}.md").write_text(f"---\nname: r-{ver}\n---\n")

        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(marketplace / "hookify-plus" / "2.0.0"))
        result = _get_plugin_rules()
        assert len(result) == 2

    def test_ignores_non_directory_entries(self, tmp_path, monkeypatch):
        """Non-directory entries in marketplace dir are skipped."""
        marketplace = tmp_path / "marketplace"
        (marketplace / "hookify-plus" / "2.0.0").mkdir(parents=True)

        # File in marketplace dir (not a plugin)
        (marketplace / "README.md").write_text("not a plugin")

        sibling_rules = marketplace / "security-hooks" / "1.0.0" / "hookify-plus"
        sibling_rules.mkdir(parents=True)
        (sibling_rules / "rule.md").write_text("---\nname: rule\n---\n")

        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(marketplace / "hookify-plus" / "2.0.0"))
        result = _get_plugin_rules()
        assert len(result) == 1


class TestDiscoverRuleFiles:
    def test_combines_all_sources(self, tmp_path, monkeypatch):
        """discover_rule_files() returns project + global + plugin rules."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("HOME", str(tmp_path / "home"))

        # Project rule
        proj_dir = tmp_path / ".claude" / "hookify-plus"
        proj_dir.mkdir(parents=True)
        (proj_dir / "proj.md").write_text("---\nname: proj\n---\n")

        # Global rule
        global_dir = tmp_path / "home" / ".claude" / "hookify-plus"
        global_dir.mkdir(parents=True)
        (global_dir / "global.md").write_text("---\nname: global\n---\n")

        # Plugin rule
        marketplace = tmp_path / "marketplace"
        (marketplace / "hookify-plus" / "2.0.0").mkdir(parents=True)
        sibling = marketplace / "my-plugin" / "1.0.0" / "hookify-plus"
        sibling.mkdir(parents=True)
        (sibling / "plugin.md").write_text("---\nname: plugin\n---\n")
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(marketplace / "hookify-plus" / "2.0.0"))

        result = discover_rule_files()
        assert len(result) == 3
