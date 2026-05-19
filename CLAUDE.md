# CLAUDE.md

## Repository Purpose

Plugin monorepo for Claude Code. Contains the hookify-plus engine and rule plugins.

## Structure

- `hookify-plus/` — Rule engine plugin (convention-based discovery)
- `security-hooks/` — 23 blocking rules (requires hookify-plus)
- `best-practices/` — 6 warning rules (requires hookify-plus)
- `tests/` — Integration tests for all rules

## Commands

```bash
# Run tests
python3 tests/helpers/run_hookify_tests.py tests/hooks/hookify_test_cases.yaml --verbose

# Run bats integration tests
bats tests/hooks/

# Run unit tests
pytest tests/unit/ -v
```

## Versioning

Plugin versions are read from `plugin.json` manifests. `claude plugins update` compares the installed version string against the manifest — same string means "already at latest" even if code changed.

**When making changes in a PR**, bump the version in both files:

1. `<plugin>/.claude-plugin/plugin.json` — the plugin's own manifest
2. `.claude-plugin/marketplace.json` — the marketplace registry

Use semver: patch for bug fixes, minor for new rules/features, major for breaking changes.

If you forget, users must uninstall/reinstall to pick up changes.

## Plugin Discovery Convention

Rules live in `hookify-plus/` directories. The engine scans:

1. `.claude/hookify-plus/*.md` — project-level
2. `~/.claude/hookify-plus/*.md` — global
3. `<sibling_plugin>/hookify-plus/*.md` — plugin-provided (same marketplace)
