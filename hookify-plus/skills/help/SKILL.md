---
name: help
description: This skill should be used when the user asks "how does hookify work", "hookify help", "what is hookify", "how to create hookify rules", "what commands does hookify have", or needs an overview of the hookify plugin system.
---

# Hookify Plugin Help

Explain how the hookify plugin works and how to use it.

## Overview

The hookify plugin makes it easy to create custom hooks that prevent unwanted behaviors. Instead of editing `hooks.json` files, create simple markdown configuration files that define patterns to watch for.

## How It Works

### Hook System

Hookify installs generic hooks that run on these events:

- **PreToolUse**: Before any tool executes (Bash, Edit, Write, etc.)
- **PostToolUse**: After a tool executes
- **Stop**: When Claude wants to stop working
- **UserPromptSubmit**: When user submits a prompt

These hooks read configuration files from `.claude/hookify-plus/*.md` and check if any rules match the current operation.

### Configuration Files

Create rules as `.md` files in the `.claude/hookify-plus/` directory:

```markdown
---
name: warn-dangerous-rm
enabled: true
event: bash
pattern: rm\s+-rf
---

Warning: Dangerous rm command detected!

This command could delete important files. Verify the path.
```

**Key fields:**

- `name`: Unique identifier for the rule
- `enabled`: true/false to activate/deactivate
- `event`: bash, file, stop, prompt, or all
- `pattern`: Regex pattern to match (case-insensitive)
- `warn_once`: Only warn once per session (optional)
- `warn_interval`: Warn every N matches; 0 = every time (optional)

The message body is what Claude sees when the rule triggers.

### Creating Rules

**Option A: Use /hookify command**

```
/hookify Don't use console.log in production files
```

This analyzes the request and creates the appropriate rule file.

**Option B: Create manually**

Create `.claude/hookify-plus/my-rule.md` with the format above.

**Option C: Analyze conversation**

```
/hookify
```

Without arguments, hookify analyzes recent conversation to find behaviors to prevent.

## Available Commands

- **`/hookify`** - Create hooks from conversation analysis or explicit instructions
- **`/hookify:help`** - Show this help
- **`/hookify:list`** - List all configured hooks
- **`/hookify:configure`** - Enable/disable existing hooks interactively

## Getting Started

1. Create a first rule:

   ```
   /hookify Warn me when I try to use rm -rf
   ```

1. Trigger it by asking Claude to run `rm -rf /tmp/test`. The warning should appear.

1. Refine the rule by editing `.claude/hookify-plus/warn-rm.md`.

1. Create more rules as unwanted behaviors are encountered.

For more examples, check the `${CLAUDE_PLUGIN_ROOT}/examples/` directory.

## Important Notes

**No Restart Needed**: Hookify rules take effect immediately on the next tool use. The hookify hooks are already loaded and read rules dynamically.

**Block or Warn**: Rules can either `block` operations (prevent execution) or `warn` (show message but allow). Set `action: block` or `action: warn` in the rule's frontmatter.

**Rule Files**: Keep rules in `.claude/hookify-plus/*.md`. Git-ignore the directory if needed.

**Disable Rules**: Set `enabled: false` in frontmatter or delete the file.

## Additional Resources

For detailed pattern syntax (Python regex), consult `references/pattern-syntax.md`.

For troubleshooting common issues, consult `references/troubleshooting.md`.

For detailed rule examples covering various use cases, consult `references/examples.md`.
