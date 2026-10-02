---
name: block-export-dump
enabled: true
event: bash
# Bare export, export -p and export -n with no names all dump exported variables
pattern: (?:^|(?<=[\n;&)`])|(?<=(?<![^\s;&|(){}`!$<>])\()|(?<=(?<![\w-])then\()|(?<=(?<![\w-])do\()|(?<=(?<![\w-])else\()|(?<=(?<![\w-])elif\()|(?<=(?<![\w-])if\()|(?<=(?<![\w-])while\()|(?<=(?<![\w-])until\()|(?<=(?<![\w-])time\()|(?<=[<>]&)[0-9-]+(?=[^\S\n])|(?<=(?<![\w\\])\|)|(?<=\$\()|(?<![\w-])(?-i:then|do|else|elif|if|while|until|time|coproc|builtin|command|eval|exec)(?=[^\S\n])|(?<![\w-])time[^\S\n]+-p(?=[^\S\n])|(?<![\w-])-[a-zA-Z]*c(?=[^\S\n])|(?<![\w-])watch(?:[^\S\n]+-\S+(?:[^\S\n]+[0-9][^\s;&|]*)?){0,4}(?=[^\S\n])|(?<![\w-])ssh[^\S\n]+\S+(?=[^\S\n])|:::(?=[^\S\n])|(?:^|(?<=\n))[^\S\n]*(?:@\w+|(?:[0-9*/,-]+[^\S\n]+){4}[0-9*/,-]+)(?=[^\S\n]))(?:[^\S\n]*(?:!|\{|[A-Za-z_]\w*=(?:"[^"\n`]*"|\'[^\'\n]*\'|\$\([^()\n]*\)|[^\s;&|`"\'()])*|[0-9]*[<>]&?[^\S\n]*(?:\$\([^()\n]*\)|[^\s;&|`()])+)(?=[^\S\n])){0,8}[^\S\n]*\\?(?-i:export)(?:[^\S\n]+(?:-(?![a-zA-Z]*[fF])[a-zA-Z]+|\+[a-zA-Z]+|--print|--))*(?:[^\S\n]*(?:$|;|&|\||\)|`|[0-9]*>[^\S\n]*\S|[0-9]*<|(?<=[^\S\n])#)|[^\S\n]*(?:\n|[\'"](?=[^\S\n]|$|[;&|)\n])))|(?<![\w-])echo[^\S\n]+\\?(?-i:export)(?:[^\S\n]+(?:-(?![a-zA-Z]*[fF])[a-zA-Z]+|\+[a-zA-Z]+|--print|--))*(?:[^\S\n]*(?:\|(?!\|)|\)|`)|(?:(?<=\s[-+][a-zA-Z])|(?<=\s[-+][a-zA-Z]{2})|(?<=\s[-+][a-zA-Z]{3})|(?<=--print)|(?<=\s--))[^\S\n]*[0-9&]*>)|(?:(?<=\s-c [\'"])|(?<=-[a-z]c [\'"])|(?<=\seval [\'"])|(?<=\sexec [\'"])|(?<=^eval [\'"]))\\?(?-i:export)(?:[^\S\n]+(?:-(?![a-zA-Z]*[fF])[a-zA-Z]+|\+[a-zA-Z]+|--print|--))*(?:[\'"](?=[^\S\n]|$|[;&|)\n])|[^\S\n]*(?:$|;|&|\||\)|`|[0-9]*>[^\S\n]*\S|[0-9]*<|(?<=[^\S\n])#))|(?:\$\(|`)(?:(?!\$\(|(?<![\w-])(?:echo|printf)[^\S\n])[^)`\n])*(?<![\w-])(?:echo|printf)[^\S\n]+[\'"]?\\?(?-i:export)(?:[^\S\n]+(?:-(?![a-zA-Z]*[fF])[a-zA-Z]+|\+[a-zA-Z]+|--print|--))*[\'"]?[^\S\n]*(?:\)|`|;|&|\|)
action: block
mask_data: true
---

🚫 **Blocked: Dumping exported variables with `export`**

**What was blocked:** `export` or `export -p` with no variable names (prints all exported variables with their values)

**Why:** This dumps ALL exported environment variables including secrets, tokens, and credentials.

**Safe alternatives:**

- List variable names only: `env | cut -d= -f1`
- Check if variable is exported: `declare -p VARNAME 2>/dev/null | grep -q 'declare -x' && echo "exported"`
- Check if variable exists: `[ -n "$VAR" ] && echo "set"`

**Note:** `export VAR=value`, `export -n VAR`, `export -f fn` and other uses that name a variable are allowed.

**False positive?** Open an issue: `gh issue create --repo anthony-spruyt/claude-plugins --title "False positive: block-export-dump" --label bug` and describe the blocked command in the body using `--body-file` to avoid re-triggering hooks.
