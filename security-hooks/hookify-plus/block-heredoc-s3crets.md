---
name: block-heredoc-secrets
enabled: true
event: bash
conditions:
  - field: command
    operator: command_match
    pattern: ' <<<?-? (?=(?:''(?:[^'']|''\"''\"'')*''|\S*)(?: |$))(?:''[^'']*|\S*)(?<!\\)\$\{?!?[A-Za-z0-9_]*(?:_PAT|TOKENS?|SECRETS?|PASSWORD|PASSWD|_PASS|_PWD|PASSPHRASE|CREDENTIALS?|PRIVATE_KEY|API_?KEY|SECRET_KEY|ACCESS_KEY|_KEY|_AUTH)[0-9]*\b(?!:?\+)'
    fallback: '<<-?[^\S\n]*(?![\''"\\])(\w{1,64})(?!\w)(?:(?!<<)[^\n])*(?:\n(?!\t*\1(?:\n|$|\)))|(?!<<)[^\n$]|\$(?!\{?[A-Za-z0-9_]*(?:_PAT|TOKENS?|SECRETS?|PASSWORD|PASSWD|_PASS|_PWD|PASSPHRASE|CREDENTIALS?|PRIVATE_KEY|API_?KEY|SECRET_KEY|ACCESS_KEY|_KEY|_AUTH)[0-9]*\b(?!:?\+)))*?\$\{?[A-Za-z0-9_]*(?:_PAT|TOKENS?|SECRETS?|PASSWORD|PASSWD|_PASS|_PWD|PASSPHRASE|CREDENTIALS?|PRIVATE_KEY|API_?KEY|SECRET_KEY|ACCESS_KEY|_KEY|_AUTH)[0-9]*\b(?!:?\+)|<<-?[^\S\n]*[\''"]?\w+(?!\w)[\''"]?(?:(?!<<)[^\n$]|\$(?!\{?[A-Za-z0-9_]*(?:_PAT|TOKENS?|SECRETS?|PASSWORD|PASSWD|_PASS|_PWD|PASSPHRASE|CREDENTIALS?|PRIVATE_KEY|API_?KEY|SECRET_KEY|ACCESS_KEY|_KEY|_AUTH)[0-9]*\b(?!:?\+)))*?\$\{?[A-Za-z0-9_]*(?:_PAT|TOKENS?|SECRETS?|PASSWORD|PASSWD|_PASS|_PWD|PASSPHRASE|CREDENTIALS?|PRIVATE_KEY|API_?KEY|SECRET_KEY|ACCESS_KEY|_KEY|_AUTH)[0-9]*\b(?!:?\+)|<<(?:(?!<<)[\s\S])*?(?:\n|;|&&|\|\|)[^\S\n]*\$\{?[A-Za-z0-9_]*(?:_PAT|TOKENS?|SECRETS?|PASSWORD|PASSWD|_PASS|_PWD|PASSPHRASE|CREDENTIALS?|PRIVATE_KEY|API_?KEY|SECRET_KEY|ACCESS_KEY|_KEY|_AUTH)[0-9]*\b(?!:?\+)|\b(?:cat|tee|base64|xxd|od|hexdump|rev|strings)\b(?:(?!\b(?:cat|tee|base64|xxd|od|hexdump|rev|strings)\b)[^\n;&|<])*<<<(?:(?!\b(?:cat|tee|base64|xxd|od|hexdump|rev|strings)\b)[^\n;&|\''"`$\\]|\\(?!(?:echo|printf)\b)[\s\S]|\''[^\'']*\''|"(?:[^"\\$`]|\\[\s\S]|\$(?!\{?[A-Za-z0-9_]*(?:_PAT|TOKENS?|SECRETS?|PASSWORD|PASSWD|_PASS|_PWD|PASSPHRASE|CREDENTIALS?|PRIVATE_KEY|API_?KEY|SECRET_KEY|ACCESS_KEY|_KEY|_AUTH)[0-9]*\b(?!:?\+))|`[^`]*`)*"|`[^`]*`|\$\((?:(?!\$\()[^()]|\([^()]*\))*\)|(?!\$\{?[A-Za-z0-9_]*(?:_PAT|TOKENS?|SECRETS?|PASSWORD|PASSWD|_PASS|_PWD|PASSPHRASE|CREDENTIALS?|PRIVATE_KEY|API_?KEY|SECRET_KEY|ACCESS_KEY|_KEY|_AUTH)[0-9]*\b(?!:?\+))\$\{[^}\n$]*\}|\$(?!\(|\{?[A-Za-z0-9_]*(?:_PAT|TOKENS?|SECRETS?|PASSWORD|PASSWD|_PASS|_PWD|PASSPHRASE|CREDENTIALS?|PRIVATE_KEY|API_?KEY|SECRET_KEY|ACCESS_KEY|_KEY|_AUTH)[0-9]*\b(?!:?\+)))*?(?:"(?:[^"\\$`]|\\[\s\S]|\$(?!\{?[A-Za-z0-9_]*(?:_PAT|TOKENS?|SECRETS?|PASSWORD|PASSWD|_PASS|_PWD|PASSPHRASE|CREDENTIALS?|PRIVATE_KEY|API_?KEY|SECRET_KEY|ACCESS_KEY|_KEY|_AUTH)[0-9]*\b(?!:?\+))|`[^`]*`)*)?\$\{?[A-Za-z0-9_]*(?:_PAT|TOKENS?|SECRETS?|PASSWORD|PASSWD|_PASS|_PWD|PASSPHRASE|CREDENTIALS?|PRIVATE_KEY|API_?KEY|SECRET_KEY|ACCESS_KEY|_KEY|_AUTH)[0-9]*\b(?!:?\+)'
action: block
mask_data: true
---

🚫 **Blocked: Heredoc referencing sensitive environment variable**

**What was blocked:** A heredoc (`<<EOF`) containing a reference to a variable that appears to contain secrets.

**Why:** Heredocs expand variables by default, which would expose the secret value in the output.

**Safe alternative using quoted delimiter:**

```bash
# Single-quoted delimiter PREVENTS variable expansion:
cat <<'EOF'
Token check: $SECRET_TOKEN will NOT expand
EOF
```

**If you need to check if a variable is set:**

```bash
[ -n "$VAR_NAME" ] && echo "set" || echo "not set"
```

**False positive?** Open an issue: `gh issue create --repo anthony-spruyt/claude-plugins --title "False positive: block-heredoc-secrets" --label bug` and describe the blocked command in the body using `--body-file` to avoid re-triggering hooks.
