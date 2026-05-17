---
name: writing-rules
description: This skill should be used when the user asks to "create a hookify rule", "write a hook rule", "configure hookify", "add a hookify rule", "hookify rule syntax", or needs guidance on hookify rule file format, frontmatter fields, and regex patterns.
---

# Writing Hookify Rules

## Overview

Hookify rules are markdown files with YAML frontmatter that define patterns to watch for and messages to display when those patterns match. Store rules as `.md` files in `.claude/hookify-plus/`. Rules are read dynamically — changes take effect on the next tool use.

## Rule File Format

### Basic Structure

```markdown
---
name: rule-identifier
enabled: true
event: bash|file|stop|prompt|all
pattern: regex-pattern-here
---

Message to show Claude when this rule triggers.
Include markdown formatting, warnings, and suggestions.
```

### Frontmatter Fields

**name** (required): Unique identifier for the rule.

- Use kebab-case: `warn-dangerous-rm`, `block-console-log`
- Start with a verb: warn, prevent, block, require, check

**enabled** (required): Boolean to activate/deactivate.

- Set `true` to activate, `false` to disable without deleting the rule.

**event** (required): Hook event to trigger on.

- `bash` — Bash tool commands
- `file` — Edit, Write, MultiEdit, Update tools
- `read` — Read, Glob, Grep, LS tools (reads, not modifications)
- `stop` — When the agent wants to stop
- `prompt` — When the user submits a prompt
- `all` — All events

**action** (optional): Behavior when the rule matches.

- `warn` — Show message but allow operation (default)
- `block` — Prevent operation (PreToolUse) or stop session (Stop events)

**warn_once** (optional): Boolean. Only warn once per session. Subsequent matches are silently ignored.

**warn_interval** (optional): Integer. Warn every N matches. Set to 0 to warn every time (default behavior).

**tool_matcher** (optional): String. Override which tools a rule matches, instead of using the default tool set for the event type.

**pattern** (simple format): Regex pattern to match (case-insensitive).

- Matches against `command` (bash) or `new_text` (file).
- Use Python regex syntax.

Example:

```yaml
event: bash
pattern: rm\s+-rf
```

### Advanced Format (Multiple Conditions)

For rules with multiple conditions, replace `pattern` with a `conditions` array. All conditions must match for the rule to trigger.

```yaml
conditions:
  - field: file_path
    operator: regex_match
    pattern: \.env$
  - field: new_text
    operator: contains
    pattern: API_KEY
```

See `references/advanced-conditions.md` for the full list of operators, fields, and examples.

## Message Body

The markdown content after frontmatter is shown to Claude when the rule triggers. Write effective messages by following these guidelines:

- Explain what was detected
- Explain why it matters
- Suggest alternatives or best practices
- Use formatting for clarity (bold, lists, code blocks)

Example:

```markdown
**Console.log detected!**

Adding console.log to production code.

**Why this matters:**

- Debug logs should not ship to production
- Console.log can expose sensitive data

**Alternatives:**

- Use a proper logging library
- Remove before committing
```

## File Organization

**Locations:**

- **Project rules:** `.claude/hookify-plus/*.md` (per-project)
- **Global rules:** `~/.claude/hookify-plus/*.md` (all projects)
- **Plugin rules:** `<sibling_plugin>/hookify-plus/*.md` (same marketplace)

**Naming convention:** `{descriptive-name}.md` inside the `hookify-plus/` directory.

**Gitignore:** Add `.claude/hookify-plus/` to `.gitignore` if rules should not be committed.

Good names: `dangerous-rm.md`, `console-log.md`, `require-tests.md`

Bad names: `rule1.md` (not descriptive), `my-rule.txt` (wrong extension)

## Workflow

### Creating a Rule

1. Identify unwanted behavior
1. Determine which tool is involved (Bash, Edit, etc.)
1. Choose event type (bash, file, stop, etc.)
1. Write a regex pattern
1. Create `.claude/hookify-plus/{name}.md` in project root
1. Test immediately — rules load dynamically on next tool use

### Disabling a Rule

- **Temporary:** Set `enabled: false` in frontmatter
- **Permanent:** Delete the `.md` file from `.claude/hookify-plus/`

## Quick Reference

**Minimum viable rule:**

```markdown
---
name: my-rule
enabled: true
event: bash
pattern: dangerous_command
---

Warning message here
```

**Event types:** `bash`, `file`, `read`, `stop`, `prompt`, `all`

**Field options:**

| Event    | Fields                                         |
| -------- | ---------------------------------------------- |
| `bash`   | `command`                                      |
| `file`   | `file_path`, `new_text`, `old_text`, `content` |
| `read`   | `file_path`                                    |
| `prompt` | `user_prompt`                                  |
| `stop`   | `reason`, `transcript`                         |

**Operators:** `regex_match`, `not_regex_match`, `contains`, `equals`, `not_contains`, `starts_with`, `ends_with`

**hookify-plus extras:** `not_regex_match` operator, `value` key alias for `pattern`, global rules in `~/.claude/`, `read` event type

## Examples

See `${CLAUDE_PLUGIN_ROOT}/examples/` for complete examples:

- `dangerous-rm.md` — Block dangerous rm commands
- `console-log-warning.md` — Warn about console.log
- `sensitive-files-warning.md` — Warn about editing .env files
- `require-tests-stop.md` — Require tests before stopping

## Additional Resources

- `references/pattern-reference.md` — Regex basics, common patterns, testing tips, and pitfalls
- `references/event-types.md` — Detailed event type guide with examples for each event
- `references/advanced-conditions.md` — Multiple conditions, operators, field reference, and examples
