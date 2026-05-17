# Pattern Syntax

Hookify patterns use Python regex syntax. All matching is **case-insensitive** (`re.IGNORECASE`).

## Common Tokens

- `\s` - whitespace
- `\.` - literal dot
- `|` - OR
- `+` - one or more
- `*` - zero or more
- `\d` - digit
- `[abc]` - character class
- `^` - start of string
- `$` - end of string
- `(...)` - capture group
- `(?:...)` - non-capturing group

## Examples

| Pattern               | Matches                        |
| --------------------- | ------------------------------ |
| `rm\s+-rf`            | "rm -rf"                       |
| `console\.log\(`      | "console.log("                 |
| \`(eval               | exec)(\`                       |
| `\.env$`              | files ending in .env           |
| `chmod\s+777`         | "chmod 777"                    |
| `\bTODO\b`            | "TODO" as a whole word         |
| `password\s*=\s*['"]` | hardcoded password assignments |

## Testing Patterns

Verify a pattern before adding it to a rule:

```bash
python3 -c "import re; print(re.search(r'your_pattern', 'test_text'))"
```

A `None` result means no match. A `Match` object means the pattern works.

## Tips

- Escape literal dots, parens, and brackets with `\`.
- Use raw strings or avoid double-escaping in YAML frontmatter.
- Start with a simple pattern, then refine to reduce false positives.
- Use `\b` word boundaries to avoid partial matches.
