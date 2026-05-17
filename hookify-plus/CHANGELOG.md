# Changelog

All notable changes to hookify-plus are documented here.

Hookify Plus originated from Anthropic's [hookify](https://github.com/anthropics/claude-code/tree/main/plugins/hookify) plugin and is now maintained independently in the [anthony-spruyt/claude-plugins](https://github.com/anthony-spruyt/claude-plugins) marketplace under standard [semver](https://semver.org/).

## [2.2.1] - 2026-05-17

### Changed

- **Docs** — Rewrote README to drop the stale "unmaintained fork" framing
  and clone+symlink install instructions. Now documents marketplace
  installation, the `.claude/hookify-plus/*.md` discovery convention, and
  standard semver versioning.

## Pre-2.x history

The entries below predate the move to this marketplace, when versions
followed an upstream-tracking `0.1.0-plus.N` scheme.

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

Standard [semver](https://semver.org/): `MAJOR.MINOR.PATCH`.

- **patch** — bug fixes
- **minor** — new rules / features
- **major** — breaking changes

(Versions before 1.0.0 used an upstream-tracking `0.1.0-plus.N` scheme; see
the pre-2.x history above.)
