# Rule Examples

## Prevent Dangerous Commands

```markdown
---
name: block-chmod-777
enabled: true
event: bash
pattern: chmod\s+777
---

Do not use chmod 777 - it is a security risk. Use specific permissions instead.
```

## Warn About Debugging Code

```markdown
---
name: warn-console-log
enabled: true
event: file
pattern: console\.log\(
---

Console.log detected. Remove debug logging before committing.
```

## Require Tests Before Stopping

```markdown
---
name: require-tests
enabled: true
event: stop
pattern: .*
---

Run tests before finishing. Ensure `npm test` or equivalent was executed.
```

## Block Hardcoded Secrets

```markdown
---
name: block-hardcoded-secrets
enabled: true
event: file
pattern: (password|secret|api_key)\s*=\s*['"][^'"]+['"]
action: block
---

Hardcoded secret detected. Use environment variables or a secrets manager instead.
```

## Warn on Force Push

```markdown
---
name: warn-force-push
enabled: true
event: bash
pattern: git\s+push\s+.*--force
---

Force push detected. Confirm this is intentional - it rewrites remote history.
```

## Block Wildcard Deletes

```markdown
---
name: block-wildcard-delete
enabled: true
event: bash
pattern: rm\s+.*\*
action: block
---

Wildcard delete detected. Specify exact files to avoid accidental data loss.
```
