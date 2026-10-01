---
name: block-env-dump
enabled: true
event: bash
# Lookahead: allow pipe to cut -d= -f1 (keys only) or wc (count only).
# -f1 boundary: require command terminator or pipe after -f1 — blocks trailing flags like --complement.
# Flags: (-0|--null|--zero|--|--unset=X|-u X) still dump all vars, so block them too.
# -i is excluded: env -i outputs empty env (no secrets) or runs a command.
pattern: (?:^|[\n;&({`]|(?<![\w\\])\||\$\(|\b(?:then|do|else|time|builtin|command|exec|nohup|sudo|xargs|nice)[^\S\n]+|[^\S\n]--[^\S\n]+|\b(?:docker|podman|kubectl)[^\S\n]+exec\b[^\n;&|]*?[^\S\n]|\bssh[^\S\n]+\S+[^\S\n]+|(?<![^\s;&|(`'"])(?:/usr)?/bin/|(?:^|(?<=\s))\\|[^\S\n]-c[^\S\n]+)[^\S\n]*[\'"]?(?-i:env)(?:[^\S\n]+(?:-0|--null|--zero|--|--unset=\S+|-u[^\S\n]+\S+))*(?:[^\S\n]*(?:$|\n|;|&(?!&)|&&|\|\||\)|`|[\'"](?:[^\S\n]|$)|[0-9&]*>[^\S\n]*\S)|[^\S\n]*\|(?!\|)(?![^\S\n]*(?:cut[^\S\n]+(?:-d=|--delimiter==)[^\S\n]+(?:-f1|--fields=1)(?:[^\S\n]*(?:$|\n|;|&&|\|\||\)|`|\|))|wc[^\S\n]+-l\b|wc[^\S\n]*(?:$|\n|;|&|\|))))
action: block
mask_data: true
---

🚫 **Blocked: Dumping environment variables**

**What was blocked:** `env` command (shows all environment variables with values)

**Why:** Environment variables often contain secrets, tokens, and credentials.

**If you need a specific variable:**

1. Ask the user: "What is the value of `$VARIABLE_NAME`?"
2. User can provide the value if it's safe to share

**Safe alternatives:**

- List variable names only: `env | cut -d= -f1`
- Check if variable exists: `[ -n "$VAR" ] && echo "set"`
- Get specific non-secret var: `echo $PATH`

**False positive?** Open an issue: `gh issue create --repo anthony-spruyt/claude-plugins --title "False positive: block-env-dump" --label bug` and describe the blocked command in the body using `--body-file` to avoid re-triggering hooks.
