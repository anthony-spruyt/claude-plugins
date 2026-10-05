---
name: block-secret-as-command
enabled: true
event: bash
# The parser gives up on a dynamic command name, so the fallback does the work
# A lone ( or backtick is not a command start: heredoc markdown writes `$X` and ($X)
# Nothing crosses ;&| even escaped, so each piece is scanned once
conditions:
  - field: command
    operator: command_match
    pattern: '^\S*\$\{?[A-Za-z0-9_]*(?:_PAT|TOKENS?|SECRETS?|PASSWORD|PASSWD|_PASS|_PWD|PASSPHRASE|CREDENTIALS?|PRIVATE_KEY|API_?KEY|SECRET_KEY|ACCESS_KEY|_KEY|_AUTH)[0-9]*\b(?!:?\+)'
    fallback: '(?:^|(?<=[\n;&|])|(?<=\$\())[^\S\n]*(?:(?:(?:eval|exec|command|builtin|nohup|sudo|doas|time|nice|xargs|env|(?:ba|z|da|k)?sh|!|\{|if|then|else|elif|while|until|do)(?:[^\S\n]+-[^\s;&|<>()]*)*|timeout(?:[^\S\n]+-[^\s;&|<>()]*)*[^\S\n]+[0-9][^\s;&|<>()]*|[A-Za-z_]\w*(?:\[[^\]\n]*\])?\+?=(?:[^\s;&|<>()''"\\]|''[^''\n;&|]*''|"(?:[^"\\\n;&|]|\\[^\n;&|])*"|\\[^\n;&|])*)[^\S\n]+)*(?![A-Za-z_]\w*(?:\[[^\]\n]*\])?\+?=)''?(?:[^\s;&|<>()''"\\$`]|''[^''\n;&|]*''|"|\\[^\n;&|]|\$(?!\{?[A-Za-z0-9_]*(?:_PAT|TOKENS?|SECRETS?|PASSWORD|PASSWD|_PASS|_PWD|PASSPHRASE|CREDENTIALS?|PRIVATE_KEY|API_?KEY|SECRET_KEY|ACCESS_KEY|_KEY|_AUTH)[0-9]*\b(?!:?\+)))*\$\{?[A-Za-z0-9_]*(?:_PAT|TOKENS?|SECRETS?|PASSWORD|PASSWD|_PASS|_PWD|PASSPHRASE|CREDENTIALS?|PRIVATE_KEY|API_?KEY|SECRET_KEY|ACCESS_KEY|_KEY|_AUTH)[0-9]*\b(?!:?\+)'
action: block
mask_data: true
---

🚫 **Blocked: Running a secret variable as a command**

**What was blocked:** a secret-looking variable (PAT, TOKEN, SECRET, PASSWORD, KEY, CREDENTIAL) where the command name goes: `$GITHUB_TOKEN`, `eval "$API_KEY"`, `sh -c "$DB_PASSWORD"`, `xargs $NPM_TOKEN`.

**Why:** Bash runs the value as a command. When it fails, the error message prints the value: `bash: ghp_abc123: command not found`.

**Still allowed:**

- Passing the secret as a value: `GH_TOKEN="$GITHUB_TOKEN" gh pr list`
- Checking it is set: `[ -n "$VAR_NAME" ] && echo set`

**False positive?** Open an issue: `gh issue create --repo anthony-spruyt/claude-plugins --title "False positive: block-secret-as-command" --label bug` and describe the blocked command in the body using `--body-file` to avoid re-triggering hooks.
