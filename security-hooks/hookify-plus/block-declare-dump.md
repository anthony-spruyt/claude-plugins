---
name: block-declare-dump
enabled: true
event: bash
# declare/typeset with no names dumps variables; -f/-F list functions only
pattern: (?:^|(?<=[\n;&){}`!])|(?<=(?<![^\s;&|(){}`!$<>])\()|(?<=(?<![\w\\])\|)|(?<=\$\()|(?<![\w-])(?-i:then|do|else|elif|if|while|until|time|coproc|builtin|command|eval|exec)(?=[^\S\n])|(?<![\w-])time[^\S\n]+-p(?=[^\S\n])|(?<![\w-])-[a-zA-Z]*c(?=[^\S\n])|(?<![\w-])watch(?:[^\S\n]+-\S+(?:[^\S\n]+[0-9][^\s;&|]*)?){0,4}(?=[^\S\n])|(?<![\w-])ssh[^\S\n]+\S+(?=[^\S\n])|:::(?=[^\S\n])|(?:^|(?<=\n))[^\S\n]*(?:@\w+|(?:[0-9*/,-]+[^\S\n]+){4}[0-9*/,-]+)(?=[^\S\n]))(?:[^\S\n]*(?:!|[A-Za-z_]\w*=(?:"[^"\n$`]*"|\'[^\'\n]*\'|[^\s;&|`$"\'(){}!<>]*)|[0-9]*[<>]&?[^\S\n]*[^\s;&|`$<>(){}!]+)(?=[^\S\n])){0,8}[^\S\n]*\\?(?-i:declare|typeset)(?:[^\S\n]+(?:-(?![a-zA-Z]*[fF])[a-zA-Z]+|\+[a-zA-Z]+|--print|--))*(?:[^\S\n]*(?:$|;|&|\||\)|`|[0-9]*>[^\S\n]*\S|[0-9]*<|(?<=[^\S\n])#)|[^\S\n]*(?:\n|[\'"](?=[^\S\n]|$|[;&|)\n])))|(?<=\becho )\\?(?-i:declare|typeset)(?:[^\S\n]+(?:-(?![a-zA-Z]*[fF])[a-zA-Z]+|\+[a-zA-Z]+|--print|--))*[^\S\n]*\|[^\S\n]*(?:\S*/)?(?:ba|z|da|k)?sh\b|(?:(?<=\s-c [\'"])|(?<=-[a-z]c [\'"])|(?<=\seval [\'"])|(?<=\sexec [\'"])|(?<=^eval [\'"]))\\?(?-i:declare|typeset)(?:[^\S\n]+(?:-(?![a-zA-Z]*[fF])[a-zA-Z]+|\+[a-zA-Z]+|--print|--))*(?:[\'"](?=[^\S\n]|$|[;&|)\n])|[^\S\n]*(?:$|;|&|\||\)|`|[0-9]*>[^\S\n]*\S|[0-9]*<|(?<=[^\S\n])#))|(?:\$\(|`)(?:(?!\$\(|(?<![\w-])(?:echo|printf)[^\S\n])[^)`\n])*(?<![\w-])(?:echo|printf)[^\S\n]+[\'"]?\\?(?-i:declare|typeset)(?:[^\S\n]+(?:-(?![a-zA-Z]*[fF])[a-zA-Z]+|\+[a-zA-Z]+|--print|--))*[\'"]?[^\S\n]*(?:\)|`|;|&|\|)
action: block
mask_data: true
---

🚫 **Blocked: Dumping variables with `declare`**

**What was blocked:** `declare`, `typeset` or `declare -p`/`-x` with no variable names (prints all variables with their values)

**Why:** This dumps ALL shell variables including secrets, tokens, and credentials.

**Safe alternatives:**

- List variable names only: `compgen -v`
- Check if variable exists: `[ -n "$VAR" ] && echo "set"`
- Check variable type: `declare -p VARNAME 2>/dev/null | cut -d= -f1`

**Note:** `declare -x VAR=1`, `declare -i VAR=1`, `declare -a ARR`, `declare -f` and other uses that name a variable are allowed.

**False positive?** Open an issue: `gh issue create --repo anthony-spruyt/claude-plugins --title "False positive: block-declare-dump" --label bug` and describe the blocked command in the body using `--body-file` to avoid re-triggering hooks.
