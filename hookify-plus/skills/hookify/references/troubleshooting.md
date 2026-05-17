# Troubleshooting

## Rule File Creation Fails

1. Check the current working directory with `pwd`
1. Ensure `.claude/` directory exists — create with `mkdir -p .claude` if needed
1. Use an absolute path if relative paths fail: `{cwd}/.claude/hookify-plus/{name}.md`
1. Verify the file was created with `ls .claude/hookify-plus/*.md`

## Rule Does Not Trigger

1. Verify the file is in the project's `.claude/hookify-plus/` directory, not the plugin's
1. Read the rule file to confirm the pattern is correct
1. Test the pattern directly:
   ```bash
   python3 -c "import re; print(re.search(r'pattern', 'test text'))"
   ```
1. Confirm `enabled: true` in frontmatter
1. Rules load dynamically — no restart is needed

## Blocking Is Too Strict

1. Change `action: block` to `action: warn` in the rule file
1. Or narrow the pattern to be more specific
1. Changes take effect on the next tool use

## Example End-to-End Workflow

**User says:** "/hookify Don't use rm -rf without asking me first"

**Expected flow:**

1. Analyze: the user wants to prevent `rm -rf` commands
1. Ask: "Should this block the command or just warn?"
1. User selects: "Just warn"
1. Create `.claude/hookify-plus/dangerous-rm.md`:

```markdown
---
name: warn-dangerous-rm
enabled: true
event: bash
pattern: rm\s+-rf
---

**Dangerous rm command detected**

A request was made to be warned before using rm -rf.
Verify the path is correct before proceeding.
```

5. Confirm: "Created hookify rule. It is active immediately — try triggering it!"

## Important Reminders

- **No restart needed:** Rules take effect immediately on the next tool use.
- **File location:** Always create files in the project's `.claude/hookify-plus/` directory, never in the plugin's.
- **Regex syntax:** Use Python regex syntax. Unquoted YAML values avoid escaping issues.
- **Action types:** `warn` (default) shows a message but allows the operation. `block` prevents the operation.
- **Testing:** Test rules immediately after creating them to verify correct behavior.
