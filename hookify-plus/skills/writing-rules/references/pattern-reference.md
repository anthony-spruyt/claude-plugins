# Pattern Writing Reference

All pattern matching is **case-insensitive** (`re.IGNORECASE`). A pattern like `todo` matches "TODO", "Todo", and "todo".

## Regex Basics

**Literal characters:** Most characters match themselves.

- `rm` matches "rm"
- `console.log` matches "console.log"

**Escape special characters with backslash:**

- `.` (any char) -> `\.` (literal dot)
- `(` `)` -> `\(` `\)` (literal parens)
- `[` `]` -> `\[` `\]` (literal brackets)

**Common metacharacters:**

- `\s` - whitespace (space, tab, newline)
- `\d` - digit (0-9)
- `\w` - word character (a-z, A-Z, 0-9, \_)
- `.` - any character
- `+` - one or more
- `*` - zero or more
- `?` - zero or one
- `|` - OR

**Examples:**

```
rm\s+-rf         Matches: rm -rf, rm  -rf
console\.log\(   Matches: console.log(
(eval|exec)\(    Matches: eval( or exec(
chmod\s+777      Matches: chmod 777, chmod  777
API_KEY\s*=      Matches: API_KEY=, API_KEY =
```

## Testing Patterns

Test regex patterns before deploying:

```bash
python3 -c "import re; print(re.search(r'your_pattern', 'test text'))"
```

Or use regex101.com with the Python flavor.

## Common Pitfalls

### Too Broad

```yaml
pattern: log # Matches "log", "login", "dialog", "catalog"
```

Better: `console\.log\(|logger\.`

### Too Specific

```yaml
pattern: rm -rf /tmp # Only matches exact path
```

Better: `rm\s+-rf`

### Escaping in YAML

- YAML quoted strings: `"pattern"` requires double backslashes `\\s`
- YAML unquoted: `pattern: \s` works as-is
- **Recommendation**: Use unquoted patterns in YAML

## Common Patterns by Category

### Dangerous Commands (bash)

- `rm\s+-rf` - recursive forced delete
- `dd\s+if=` - disk overwrite
- `mkfs` - filesystem format
- `sudo\s+` - privilege escalation
- `su\s+` - user switch
- `chmod\s+777` - world-writable permissions
- `chown\s+root` - root ownership change

### Debug Code (file)

- `console\.log\(` - JS debug logging
- `debugger` - JS debugger statement
- `print\(` - Python debug print

### Security Risks (file)

- `eval\(` - code execution
- `innerHTML\s*=` - XSS vector
- `dangerouslySetInnerHTML` - React XSS vector

### Sensitive Files (file)

- `\.env$` - environment files
- `credentials` - credential files
- `\.pem$` - certificate/key files
- `node_modules/` - vendored dependencies
- `dist/` - build output
- `build/` - build output
