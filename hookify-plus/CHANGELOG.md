# Changelog

All notable changes to hookify-plus are documented here.

Based on upstream [hookify 0.1.0](https://github.com/anthropics/claude-code/tree/main/plugins/hookify).

## [0.1.0-plus.4] - 2026-01-25

### Added

- **Rate limiting for warnings** - New `warn_once` and `warn_interval` fields reduce context waste
  - `warn_once: true` - Only warn once per agent session
  - `warn_interval: N` - Warn every N matches
- **State management** - PPID-scoped state in `/tmp/` with 24h TTL
  - Main agent and subagents have independent warning state
  - Auto-cleanup of stale state files

### Fixed

- **Proper #12446 fix** - Messages now use stderr + exit 2 instead of stdout + exit 0
  - Previous fix only added `permissionDecisionReason` which didn't work
  - Now Claude actually sees block/warn messages

## [0.1.0-plus.3] - 2025-01-16

### Fixed

- **Import paths for symlink compatibility** - Changed `from hookify.core` to `from core` so plugin works when symlinked with different directory name

## [0.1.0-plus.2] - 2025-01-16

### Fixed

- **Python 3.8 compatibility** - Added `from __future__ import annotations` (issue #14588)
- **Claude sees block reasons** - Added `permissionDecisionReason` to hook output (issue #12446)
- **Windows paths with spaces** - Quoted `${CLAUDE_PLUGIN_ROOT}` in hooks.json (issue #16152)
- **Example file operator** - Changed `not_contains` to `not_regex_match` in require-tests example (issue #13464)

## [0.1.0-plus.1] - 2025-01-16

### Added

- **`not_regex_match` operator** - Exclude patterns (e.g., skip test files)
- **`value` key in conditions** - Alias for `pattern`, clearer for non-regex operators
- **`read` event type** - Separate event for Read/Glob/Grep/LS tools
- **Global rules** - Rules in `~/.claude/` apply to all projects (PR #13916)
- **Update tool support** - File event fires for Update tool (PR #16081)

### Fixed

- **Read tools event mapping** - Read/Glob/Grep now fire `read` event, not `file`
- **Write tool `new_text` field** - Correctly extracts content from Write tool

## [0.1.0] - Upstream

Original hookify plugin from Anthropic.

---

## Version Scheme

`0.1.0-plus.N` where:

- `0.1.0` = upstream hookify version this is based on
- `plus.N` = hookify-plus patch number

When upstream releases 0.2.0, we'll rebase and become `0.2.0-plus.1`.
