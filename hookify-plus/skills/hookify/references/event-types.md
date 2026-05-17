# Event Types Reference

## bash

Match Bash tool commands. The `pattern` field matches against the `command` field.

```markdown
---
event: bash
pattern: rm\s+-rf|chmod\s+777
---

Dangerous command detected!
```

**Common patterns:**

- Dangerous commands: `rm\s+-rf`, `dd\s+if=`, `mkfs`
- Privilege escalation: `sudo\s+`, `su\s+`
- Permission changes: `chmod\s+777`, `chown\s+root`
- Package installs: `npm\s+install\s+`, `pip\s+install`

## file

Match Edit, Write, MultiEdit, and Update operations. The `pattern` field matches against `new_text` by default. Use `conditions` to match against `file_path`, `old_text`, or `content`.

```markdown
---
event: file
pattern: console\.log\(|eval\(|innerHTML\s*=
---

Potentially problematic code pattern detected!
```

**With conditions (match file path and content):**

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

## read

Match Read, Glob, Grep, and LS tool invocations. The `pattern` field matches against `file_path`.

```markdown
---
event: read
pattern: \.pem$|\.key$|id_rsa
---

Reading a sensitive key file. Ensure contents are not logged or exposed.
```

## stop

Match when the agent wants to stop. Use for completion checklists and process enforcement. The `pattern` field matches against the `reason` field. The `transcript` field contains the conversation transcript.

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

## prompt

Match user prompt content. The `pattern` field matches against `user_prompt`.

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

## all

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
