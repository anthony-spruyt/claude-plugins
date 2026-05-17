---
name: configure
description: This skill should be used when the user asks to "enable a hookify rule", "disable a hookify rule", "toggle hookify rules", or "configure hookify rules interactively".
---

# Configure Hookify Rules

Load the `hookify-plus:writing-rules` skill first to understand rule format.

Enable or disable existing hookify rules via an interactive selection interface.

## Steps

### 1. Find Existing Rules

Use Glob tool to find all hookify rule files:

```
pattern: ".claude/hookify-plus/*.md"
```

If no rules found, inform the user:

```
No hookify rules configured yet. Use `/hookify` to create your first rule.
```

### 2. Read Current State

For each rule file:

- Read the file
- Extract `name` and `enabled` fields from frontmatter
- Build a list of rules with current state

### 3. Present Interactive Selection

Use AskUserQuestion to let the user select rules to toggle:

```json
{
  "questions": [
    {
      "question": "Which rules would you like to enable or disable?",
      "header": "Configure",
      "multiSelect": true,
      "options": [
        {
          "label": "warn-dangerous-rm (currently enabled)",
          "description": "Warns about rm -rf commands"
        },
        {
          "label": "warn-console-log (currently disabled)",
          "description": "Warns about console.log in code"
        }
      ]
    }
  ]
}
```

Format each option as:

- **Label:** `{rule-name} (currently {enabled|disabled})`
- **Description:** Brief summary from the rule's message or pattern

### 4. Parse Selection and Toggle

For each selected rule, determine its current state from the label and invert it: enabled becomes disabled, disabled becomes enabled.

### 5. Update Rule Files

Read each rule file with the Read tool, then use the Edit tool to flip the `enabled` frontmatter field. Handle both quoted and unquoted values.

**Edit pattern for enabling:**

```
old_string: "enabled: false"
new_string: "enabled: true"
```

**Edit pattern for disabling:**

```
old_string: "enabled: true"
new_string: "enabled: false"
```

### 6. Confirm Changes

Display a summary of what changed:

```
## Hookify Rules Updated

**Enabled:**
- warn-console-log

**Disabled:**
- warn-dangerous-rm

**Unchanged:**
- require-tests

Changes apply immediately - no restart needed.
```

## Important Notes

- Changes take effect immediately on next tool use.
- To manually edit rules, modify files in `.claude/hookify-plus/` directly.
- To permanently remove a rule, delete its `.md` file from `.claude/hookify-plus/`.
- Run `/hookify:list` to see all configured rules.
- If no rules are selected, report that no changes were made.
- On file read/write errors, report the specific error and suggest manual editing as fallback.
