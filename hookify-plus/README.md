# Hookify Plus

![Version](https://img.shields.io/badge/version-2.2.1-blue)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**A rule engine for Claude Code with convention-based rule discovery.**

Hookify Plus turns markdown files with YAML frontmatter into PreToolUse / PostToolUse / Stop / UserPromptSubmit hooks. Write a rule, drop it in a `hookify-plus/` directory, and it's active — no hook wiring required.

It originated from Anthropic's [hookify](https://github.com/anthropics/claude-code/tree/main/plugins/hookify) plugin and now ships independently with added features and fixes (see [Credits](#credits)).

## What You Get

| Feature           | What it does                                             |
| ----------------- | -------------------------------------------------------- |
| `not_regex_match` | Exclude patterns (e.g., skip test files from rules)      |
| `value` key       | Clearer syntax for non-regex operators                   |
| `read` event      | Separate event for Read/Glob/Grep/LS (no false triggers) |
| Global rules      | Rules in `~/.claude/` apply to ALL projects              |
| `Update` tool     | File events also fire for the Update tool                |
| `warn_once`       | Rate limiting — only warn once per session               |
| `warn_interval`   | Rate limiting — warn every N matches                     |
| stderr + exit 2   | Claude actually sees block/warn messages ([#12446])      |

[#12446]: https://github.com/anthropics/claude-code/issues/12446

---

## Installation

Hookify Plus is distributed through this marketplace:

```bash
/plugin marketplace add anthony-spruyt/claude-plugins
```

Then enable **hookify-plus** in your Claude Code settings. Companion rule
plugins from the same marketplace (`security-hooks`, `best-practices`) are
discovered automatically once the engine is enabled.

Run `claude plugins update` to pick up new versions.

---

## Quick Start

Create your first rule:

```bash
mkdir -p .claude/hookify-plus
cat > .claude/hookify-plus/warn-rm.md << 'EOF'
---
name: warn-dangerous-rm
enabled: true
event: bash
pattern: rm\s+-rf
action: warn
---
⚠️ **Dangerous rm command!** Double-check the path before proceeding.
EOF
```

The rule is active immediately — no restart needed.

---

## Rule Syntax

Rules are markdown files with YAML frontmatter:

```markdown
---
name: rule-identifier
enabled: true
event: bash|file|read|stop|prompt|all
action: warn|block
pattern: regex-pattern
---

Message shown to Claude when rule triggers.
Supports **markdown** formatting.
```

### Multiple Conditions

```yaml
---
name: warn-env-changes
enabled: true
event: file
action: warn
conditions:
  - field: file_path
    operator: regex_match
    pattern: \.env$
  - field: file_path
    operator: not_regex_match
    pattern: \.example$
---
You're editing a .env file. Make sure it's in .gitignore!
```

### Event Types

| Event    | Triggers On                    |
| -------- | ------------------------------ |
| `bash`   | Bash tool                      |
| `file`   | Edit, Write, MultiEdit, Update |
| `read`   | Read, Glob, Grep, LS           |
| `stop`   | Agent completion               |
| `prompt` | User prompt submit             |
| `all`    | All of the above               |

### Operators

| Operator          | Description             |
| ----------------- | ----------------------- |
| `regex_match`     | Pattern matches (regex) |
| `not_regex_match` | Pattern does NOT match  |
| `contains`        | Substring present       |
| `not_contains`    | Substring NOT present   |
| `equals`          | Exact match             |
| `starts_with`     | Prefix match            |
| `ends_with`       | Suffix match            |

### Rate Limiting

Reduce context waste from repetitive warnings with rate limiting:

```yaml
---
name: warn-use-glob-tool
enabled: true
event: bash
pattern: (^|\s)(find|ls)\s+\S
action: warn
warn_once: true # Only warn once per session
# OR
warn_interval: 5 # Warn every 5th match
---
Use the Glob tool instead of find/ls for better performance.
```

| Field           | Type | Default | Description                           |
| --------------- | ---- | ------- | ------------------------------------- |
| `warn_once`     | bool | false   | Only warn once per agent session      |
| `warn_interval` | int  | 0       | Warn every N matches (0 = every time) |

**How it works:**

- State stored in `/tmp/claude-hookify-state-{ppid}.json`
- PPID-scoped: main agent and subagents have independent state
- 24-hour TTL with auto-cleanup
- `warn_once: true` takes precedence over `warn_interval`

### Fields by Event

| Event    | Available Fields                               |
| -------- | ---------------------------------------------- |
| `bash`   | `command`                                      |
| `file`   | `file_path`, `new_text`, `old_text`, `content` |
| `read`   | `file_path`                                    |
| `stop`   | `reason`, `transcript`                         |
| `prompt` | `user_prompt`                                  |

---

## Rule Discovery

The engine scans three locations, in order:

| Location                       | Scope                                     |
| ------------------------------ | ----------------------------------------- |
| `.claude/hookify-plus/*.md`    | Current project only                      |
| `~/.claude/hookify-plus/*.md`  | All projects (global)                     |
| `<sibling_plugin>/hookify-plus/*.md` | Provided by other plugins in the same marketplace |

This is how `security-hooks` and `best-practices` ship their rules — they're
plain rule files the engine picks up automatically.

---

## Versioning

Standard [semver](https://semver.org/): `MAJOR.MINOR.PATCH`.

- **patch** — bug fixes
- **minor** — new rules / features
- **major** — breaking changes

The version is read from `.claude-plugin/plugin.json`. `claude plugins update`
compares the installed version string against the manifest, so a version bump
is required for users to pick up changes.

---

## Credits

| Contributor                                          | Contribution                                                                             |
| ---------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| [@adrozdenko](https://github.com/adrozdenko)         | `not_regex_match`, `value` key, `read` event                                             |
| [@kp222x](https://github.com/kp222x)                 | Global rules ([#13916](https://github.com/anthropics/claude-code/pull/13916))            |
| [@heathdutton](https://github.com/heathdutton)       | Write fix + Update tool ([#16081](https://github.com/anthropics/claude-code/pull/16081)) |
| [@anthony-spruyt](https://github.com/anthony-spruyt) | Maintainer; rate limiting (`warn_once`, `warn_interval`), stderr + exit 2 fix for [#12446](https://github.com/anthropics/claude-code/issues/12446) |

## Contributing

1. Fork [anthony-spruyt/claude-plugins](https://github.com/anthony-spruyt/claude-plugins)
2. Make your changes
3. Bump the version in `hookify-plus/.claude-plugin/plugin.json` **and** `.claude-plugin/marketplace.json`
4. Submit a PR

## License

MIT
