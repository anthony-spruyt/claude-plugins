# Advanced Conditions Format

## Overview

For rules requiring multiple conditions, use the `conditions` array instead of a single `pattern` field. All conditions must match for the rule to trigger.

## Structure

```markdown
---
name: warn-env-file-edits
enabled: true
event: file
conditions:
  - field: file_path
    operator: regex_match
    pattern: \.env$
  - field: new_text
    operator: contains
    pattern: API_KEY
---

Adding an API key to a .env file. Ensure this file is in .gitignore!
```

## Condition Fields

### field

Specifies which input field to check.

| Event    | Available Fields                               |
| -------- | ---------------------------------------------- |
| `bash`   | `command`                                      |
| `file`   | `file_path`, `new_text`, `old_text`, `content` |
| `read`   | `file_path`                                    |
| `prompt` | `user_prompt`                                  |
| `stop`   | `reason`, `transcript`                         |

### operator

Specifies how to match.

| Operator          | Description                                                    |
| ----------------- | -------------------------------------------------------------- |
| `regex_match`     | Python regex pattern matching                                  |
| `not_regex_match` | Pattern must NOT match (regex) -- hookify-plus                 |
| `contains`        | Substring check                                                |
| `equals`          | Exact string match                                             |
| `not_contains`    | Substring must NOT be present                                  |
| `starts_with`     | Prefix check                                                   |
| `ends_with`       | Suffix check                                                   |
| `command_match`   | Regex matches any clean line of a Bash command -- hookify-plus |
| `glob_overflow`   | A glob or brace expands past the limits -- hookify-plus        |

### command_match / fallback

For `field: command`, the engine parses the command into "clean lines": one per simple command bash would run, quotes removed, wrappers (`sudo`, `bash -c`, `eval`, ...) unwrapped, redirects and pipes kept. `sudo -E e''nv | wc -l` gives `sudo -E env | wc -l`, `env | wc -l` and `wc -l`. The condition matches if `pattern` regex-searches any clean line. If the command can't be parsed, `fallback` (or
`pattern` if there is no `fallback`) is matched against the raw command instead. That raw command is masked when the rule sets `mask_data: true`. Block rules also match `pattern` on each piece of the unparsed command that parses on its own. On other fields, `command_match` behaves like `regex_match`.

```yaml
conditions:
  - field: command
    operator: command_match
    pattern: '^(env|printenv)( -\S+)*$'
    fallback: '<old raw-command regex>'
```

Quote regexes in single quotes; write a literal `'` as `''`.

### pattern / value

Provide the match target.

- Use `pattern` for regex-based operators (`regex_match`, `not_regex_match`, `command_match`).
- Use `value` for string-based operators (`contains`, `equals`, `not_contains`, `starts_with`, `ends_with`). The `pattern` key also works here, but `value` is more explicit. -- hookify-plus

## Examples

### Exclude a Directory from a File Rule

```yaml
conditions:
  - field: file_path
    operator: not_regex_match
    pattern: node_modules/
  - field: new_text
    operator: regex_match
    pattern: console\.log\(
```

### Match TypeScript Files Only

```yaml
conditions:
  - field: file_path
    operator: ends_with
    value: .ts
  - field: new_text
    operator: contains
    value: TODO
```

### Block Writing Secrets to Non-env Files

```yaml
conditions:
  - field: file_path
    operator: not_regex_match
    pattern: \.env
  - field: new_text
    operator: regex_match
    pattern: (password|secret|api_key)\s*=\s*['"].+['"]
```

## Condition Logic

All conditions are ANDed together. There is no OR combinator at the condition level. To express OR logic, create separate rules or use regex alternation (`|`) within a single condition's pattern.
