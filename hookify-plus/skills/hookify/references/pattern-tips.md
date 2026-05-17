# Pattern Writing Tips

All pattern matching is **case-insensitive** (`re.IGNORECASE`). A pattern like `todo` matches "TODO", "Todo", and "todo".

## Bash Patterns

Match dangerous or unwanted commands:

- Destructive operations: `rm\s+-rf|chmod\s+777|dd\s+if=`
- Package management: `npm\s+install\s+|pip\s+install`
- System commands: `sudo\s+|su\s+|systemctl`

## File Patterns

Match code patterns in edits:

- Debug code: `console\.log\(|eval\(|innerHTML\s*=`
- File paths: `\.env$|\.git/|node_modules/`
- Security: `(password|secret|api_key)\s*=\s*['"].+['"]`

## Stop Patterns

Stop patterns match broadly since they enforce completion criteria:

- Catch-all: `.*` (always triggers before stopping)
- Specific: match stop reason text

## Testing Patterns

Test regex patterns before deploying a rule:

```bash
python3 -c "import re; print(re.search(r'your_pattern', 'test text'))"
```

Or use regex101.com with the Python flavor selected.

## Common Pitfalls

### Too Broad

```yaml
pattern: log  # Matches "log", "login", "dialog", "catalog"
```

Better: `console\.log\(|logger\.`

### Too Specific

```yaml
pattern: rm -rf /tmp  # Only matches exact path
```

Better: `rm\s+-rf`

### Escaping in YAML

- Unquoted YAML values: `pattern: \s` works as-is (recommended)
- Quoted YAML strings: `"pattern"` requires double backslashes `\\s`
- Recommendation: use unquoted patterns to avoid escaping issues

## Regex Quick Reference

| Syntax | Meaning        | Example          |
| ------ | -------------- | ---------------- |
| `\s`   | Whitespace     | `rm\s+-rf`       |
| `\d`   | Digit          | `chmod\s+\d{3}`  |
| `\w`   | Word character | `\w+_KEY`        |
| `.`    | Any character  | `console\.log`   |
| `+`    | One or more    | `\s+`            |
| `*`    | Zero or more   | `\s*=`           |
| `?`    | Zero or one    | `https?://`      |
| \`     | \`             | OR               |
| `\.`   | Literal dot    | `console\.log\(` |
| `\(`   | Literal paren  | `eval\(`         |
