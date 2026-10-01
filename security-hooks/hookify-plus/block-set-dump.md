---
name: block-set-dump
enabled: true
event: bash
pattern: (?:^|[\n;&({`)]|(?<![\w\\])\||\$\(|\b(?:then|do|else|time|builtin|command|exec|eval|nohup|sudo|xargs|nice|timeout(?:[^\S\n]+-\S+)*[^\S\n]+\S+|watch(?:[^\S\n]+-\S+)*)[^\S\n]+|(?:^|\n)[^\S\n]*(?:@\w+|(?:[0-9*/,-]+[^\S\n]+){4}[0-9*/,-]+)[^\S\n]+|[^\S\n]--[^\S\n]+|\b(?:docker|podman|kubectl)[^\S\n]+exec\b[^\n;&|]*?[^\S\n]|\bssh[^\S\n]+\S+[^\S\n]+|(?<![^\s;&|(`'"])(?:/usr)?/bin/|(?:^|(?<=\s))\\|[^\S\n]-c[^\S\n]+)[^\S\n]*[\'"]?(?-i:set)(?:[^\S\n]*(?:$|\n|;|&|\|(?!\|)|\|\||[0-9]*>|\)|`|[\'"](?:[^\S\n]|$)))
action: block
mask_data: true
---

🚫 **Blocked: Dumping shell variables with `set`**

**What was blocked:** The `set` command without arguments, which dumps ALL shell variables and functions including secrets.

**Why:** `set` outputs every variable in the shell environment, including sensitive values like tokens, passwords, and API keys.

**If you need to:**

1. **Check shell options:** `set -o` (lists option settings, not variables)
2. **Check if a variable is set:** `[ -n "$VAR" ] && echo "set"`
3. **List variable names only:** `compgen -v` or `env | cut -d= -f1`

**Note:** `set -e`, `set -x`, `set -o pipefail` and other option-setting uses are allowed.

**False positive?** Open an issue: `gh issue create --repo anthony-spruyt/claude-plugins --title "False positive: block-set-dump" --label bug` and describe the blocked command in the body using `--body-file` to avoid re-triggering hooks.
