# CLAUDE.md

## Repository Purpose

Plugin monorepo for Claude Code. Contains the hookify-plus engine and rule plugins.

## Structure

- `hookify-plus/` — Rule engine plugin (convention-based discovery)
- `security-hooks/` — 32 blocking rules (requires hookify-plus)
- `best-practices/` — 4 warning rules (requires hookify-plus)
- `agent-kit/` — Progress notes hooks, `bin/` helper scripts, `writing-agents` skill (standalone)
- `tests/` — Integration tests for all rules

## Commands

```bash
# Run tests
python3 tests/helpers/run_hookify_tests.py tests/hooks/hookify_test_cases.yaml --verbose

# Run bats integration tests
bats tests/hooks/

# Run agent-kit tests
bats tests/agent-kit/

# Run unit tests
pytest tests/unit/ -v

# Replay real session logs through the rules (see the replay-logs skill)
python3 tests/helpers/replay_transcripts.py --exclude-project claude-plugins

# Fuzz the rules: speed (slow regexes), crash (parser), bypass (real leaks no rule blocks)
python3 tests/helpers/fuzz_rules.py speed|crash|bypass
```

## Versioning

Plugin versions are read from `plugin.json` manifests. `claude plugins update` compares the installed version string against the manifest — same string means "already at latest" even if code changed.

**Do not bump versions in PRs.** [release-please](https://github.com/googleapis/release-please) owns them (`release-please-config.json`, `.release-please-manifest.json`):

- Each plugin directory is a package. A commit touching it counts toward its next release
- The PR title sets the bump: `fix:` patch, `feat:` minor, `feat!:` or a `BREAKING CHANGE:` footer major. `docs:`, `chore:`, `ci:`, `test:` release nothing
- release-please keeps one release PR open that writes `version` in each `<plugin>/.claude-plugin/plugin.json` and a `CHANGELOG.md`. Merging it ships
- `.claude-plugin/marketplace.json` entries carry no `version`; `plugin.json` would override it anyway

## Plugin Discovery Convention

Rules live in `hookify-plus/` directories. The engine scans:

1. `.claude/hookify-plus/*.md` — project-level
2. `~/.claude/hookify-plus/*.md` — global
3. `<sibling_plugin>/hookify-plus/*.md` — plugin-provided (same marketplace)
