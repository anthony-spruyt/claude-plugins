# Event Type Guide

## bash Events

Match Bash command patterns.

```markdown
---
event: bash
pattern: sudo\s+|rm\s+-rf|chmod\s+777
---

Dangerous command detected!
```

**Common patterns:**

- Dangerous commands: `rm\s+-rf`, `dd\s+if=`, `mkfs`
- Privilege escalation: `sudo\s+`, `su\s+`
- Permission issues: `chmod\s+777`, `chown\s+root`

## file Events

Match Edit, Write, MultiEdit, and Update operations.

```markdown
---
event: file
pattern: console\.log\(|eval\(|innerHTML\s*=
---

Potentially problematic code pattern detected!
```

**Match on different fields using conditions:**

```markdown
---
event: file
conditions:
  - field: file_path
    operator: regex_match
    pattern: \.tsx?$
  - field: new_text
    operator: regex_match
    pattern: console\.log\(
---

Console.log in TypeScript file!
```

**Common patterns:**

- Debug code: `console\.log\(`, `debugger`, `print\(`
- Security risks: `eval\(`, `innerHTML\s*=`, `dangerouslySetInnerHTML`
- Sensitive files: `\.env$`, `credentials`, `\.pem$`
- Generated files: `node_modules/`, `dist/`, `build/`

## read Events

Match Read, Glob, Grep, and LS tool invocations.

```markdown
---
event: read
pattern: \.pem$|\.key$|id_rsa
---

Reading a sensitive key file. Ensure contents are not logged or exposed.
```

## stop Events

Match when the agent wants to stop (completion checks). The `pattern` field matches against the `reason` field. The `transcript` field contains the conversation transcript.

```markdown
---
event: stop
pattern: .*
---

Before stopping, verify:

- [ ] Tests were run
- [ ] Build succeeded
- [ ] Documentation updated
```

**Use for:**

- Reminders about required steps
- Completion checklists
- Process enforcement

## prompt Events

Match user prompt content.

```markdown
---
event: prompt
conditions:
  - field: user_prompt
    operator: contains
    pattern: deploy to production
---

Production deployment checklist:

- [ ] Tests passing?
- [ ] Reviewed by team?
- [ ] Monitoring ready?
```

## all Events

Match every event type. Use sparingly — triggers on all tool invocations.

```markdown
---
event: all
pattern: .*secret.*
---

Possible secret detected in operation. Verify no credentials are exposed.
```

## Field Reference by Event

| Event    | Available Fields                               |
| -------- | ---------------------------------------------- |
| `bash`   | `command`                                      |
| `file`   | `file_path`, `new_text`, `old_text`, `content` |
| `read`   | `file_path`                                    |
| `prompt` | `user_prompt`                                  |
| `stop`   | `reason`, `transcript`                         |
| `all`    | _(all fields from the triggering event)_       |
