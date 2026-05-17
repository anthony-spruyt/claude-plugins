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

## Plugin Discovery Convention

Rules live in `hookify-plus/` directories. The engine scans:
1. `.claude/hookify-plus/*.md` — project-level
2. `~/.claude/hookify-plus/*.md` — global
3. `<sibling_plugin>/hookify-plus/*.md` — plugin-provided (same marketplace)
