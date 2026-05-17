---
name: list
description: This skill should be used when the user asks to "list hookify rules", "show my hooks", "what hookify rules are configured", "show active rules", or invokes /hookify:list.
---

# List Hookify Rules

**Load hookify-plus:writing-rules skill first** to understand rule format.

Display all configured hookify rules in the project.

## Steps

1. Use Glob tool to find all hookify rule files:

   ```
   pattern: ".claude/hookify-plus/*.md"
   ```

1. For each file found:

   - Read the file with the Read tool.
   - Extract frontmatter fields: name, enabled, event, pattern.
   - Extract message preview (first 100 chars).

1. Present results in a table:

```
## Configured Hookify Rules

| Name | Enabled | Event | Pattern | File |
|------|---------|-------|---------|------|
| warn-dangerous-rm | ✅ Yes | bash | rm\s+-rf | dangerous-rm.md |
| warn-console-log | ✅ Yes | file | console\.log\( | console-log.md |
| check-tests | ❌ No | stop | .* | require-tests.md |

**Total**: 3 rules (2 enabled, 1 disabled)
```

4. For each rule, show a brief preview:

```
### warn-dangerous-rm
**Event**: bash
**Pattern**: `rm\s+-rf`
**Message**: "⚠️ **Dangerous rm command detected!** This command could delete..."

**Status**: ✅ Active
**File**: .claude/hookify-plus/dangerous-rm.md
```

5. Add helpful footer:

```
---

To modify a rule: Edit the `.md` file in `.claude/hookify-plus/` directly
To disable a rule: Set `enabled: false` in frontmatter
To enable a rule: Set `enabled: true` in frontmatter
To delete a rule: Remove the `.md` file from `.claude/hookify-plus/`
To create a rule: Use `/hookify` command

**Remember**: Changes take effect immediately - no restart needed
```

## If No Rules Found

If no hookify rules exist, display:

```
## No Hookify Rules Configured

No hookify rules created yet.

To get started:
1. Use `/hookify` to analyze conversation and create rules
2. Or manually create `.claude/hookify-plus/my-rule.md` files
3. See `/hookify:help` for documentation

Example:
```

/hookify Warn me when I use console.log

```

Check `${CLAUDE_PLUGIN_ROOT}/examples/` for example rule files.
```
