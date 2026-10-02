---
name: block-set-dump
enabled: true
event: bash
pattern: (?:^|(?<=[\n;&(){}`!])|(?<=(?<![\w\\])\|)|(?<=\$\()|(?<![\w-])(?-i:then|do|else|elif|if|while|until|time|coproc|builtin|command|eval|exec)(?=[^\S\n])|(?<![\w-])time[^\S\n]+-p(?=[^\S\n])|(?<![\w-])-[a-zA-Z]*c(?=[^\S\n])|(?<![\w-])watch(?:[^\S\n]+-\S+(?:[^\S\n]+[0-9][^\s;&|]*)?)*(?=[^\S\n])|(?<![\w-])ssh[^\S\n]+\S+(?=[^\S\n])|:::(?=[^\S\n])|(?:^|(?<=\n))[^\S\n]*(?:@\w+|(?:[0-9*/,-]+[^\S\n]+){4}[0-9*/,-]+)(?=[^\S\n]))(?:[^\S\n]*(?:!|[A-Za-z_]\w*=(?:"[^"\n$`]*"|\'[^\'\n]*\'|[^\s;&|`$"\'(]*)|[0-9]*[<>]&?[^\S\n]*[^\s;&|`$]+)(?=[^\S\n])){0,8}[^\S\n]*\\?(?-i:set)(?:[^\S\n]*(?:$|;|&|\||\)|`|[0-9]*>[^\S\n]*\S|[0-9]*<|(?<=[^\S\n])#)|[^\S\n]*(?:\n|[\'"](?=[^\S\n]|$|[;&|)\n])))|(?<=\becho )\\?(?-i:set)[^\S\n]*(?:\|(?!\|)|[0-9&]*>|\)|`)|(?:(?<=\s-c [\'"])|(?<=-[a-z]c [\'"])|(?<=\seval [\'"])|(?<=\sexec [\'"])|(?<=^eval [\'"]))\\?(?-i:set)(?:[\'"](?=[^\S\n]|$|[;&|)\n])|[^\S\n]*(?:$|;|&|\||\)|`|[0-9]*>[^\S\n]*\S|[0-9]*<|(?<=[^\S\n])#))|(?:\$\(|`)(?:(?!\$\(|(?<![\w-])(?:echo|printf)[^\S\n])[^)`\n])*(?<![\w-])(?:echo|printf)[^\S\n]+[\'"]?\\?(?-i:set)[\'"]?[^\S\n]*(?:\)|`|;|&|\|)
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
