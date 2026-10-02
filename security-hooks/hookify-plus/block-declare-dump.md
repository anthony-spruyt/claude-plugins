---
name: block-declare-dump
enabled: true
event: bash
# declare/typeset/readonly with no names dumps variables; -f/-F list functions only
# declare -p $(compgen -v) names every variable, so -p with a command substitution argument counts as a dump
# echo/parallel branches: the parser can't see code saved to a file for later or run by parallel, or rc/.sh files that get sourced
conditions:
  - field: command
    operator: command_match
    pattern: '^(?:declare|typeset|readonly)(?: [-+][^\s=fF]*)*(?: (?:\d*|&)[<>].*| \|.*)?$|^(?:declare|typeset|readonly)(?: [-+][^\s=fF]*)* -[^\s=fF]*p[^\s=fF]*(?: [^|]*)?(?:\$\(|`)|^echo (?:declare|typeset|readonly)(?:(?: [-+][^\s=fF]*)* (?:\d*|&)>[>|]? \S*(?:rc|profile|login|env|\.(?:ba|da|k|z)?sh)|(?: [-+][^\s=fF]*)+ (?:\d*|&)>)(?: |$)|^parallel (?:(?!::: ).)*::: (?:.*? )?(?:declare|typeset|readonly)(?: [-+][^\s=fF]*)*(?: |$)'
    fallback: (?:^|(?<=[\n;&)`])|(?<=(?<![^\s;&|(){}`!$<>])\()|(?<=(?<![\w-])then\()|(?<=(?<![\w-])do\()|(?<=(?<![\w-])else\()|(?<=(?<![\w-])elif\()|(?<=(?<![\w-])if\()|(?<=(?<![\w-])while\()|(?<=(?<![\w-])until\()|(?<=(?<![\w-])time\()|(?<=[<>]&)[0-9-]+(?=[^\S\n])|(?<=(?<![\w\\])\|)|(?<=\$\()|(?<![\w-])(?-i:then|do|else|elif|if|while|until|time|coproc|builtin|command|eval|exec)(?=[^\S\n])|(?<![\w-])time[^\S\n]+-p(?=[^\S\n])|(?<![\w-])-[a-zA-Z]*c(?=[^\S\n])|(?<![\w-])watch(?:[^\S\n]+-\S+(?:[^\S\n]+[0-9][^\s;&|]*)?){0,4}(?=[^\S\n])|(?<![\w-])ssh[^\S\n]+\S+(?=[^\S\n])|:::(?=[^\S\n])|(?:^|(?<=\n))[^\S\n]*(?:@\w+|(?:[0-9*/,-]+[^\S\n]+){4}[0-9*/,-]+)(?=[^\S\n]))(?:[^\S\n]*(?:!|\{|[A-Za-z_]\w*=(?:"[^"\n`]*"|\'[^\'\n]*\'|\$\([^()\n]*\)|[^\s;&|`"\'()])*|[0-9]*[<>]&?[^\S\n]*(?:\$\([^()\n]*\)|[^\s;&|`()])+)(?=[^\S\n])){0,8}[^\S\n]*\\?(?-i:declare|typeset)(?:[^\S\n]+(?:-(?![a-zA-Z]*[fF])[a-zA-Z]+|\+[a-zA-Z]+|--print|--))*(?:[^\S\n]*(?:$|;|&|\||\)|`|[0-9]*>[^\S\n]*\S|[0-9]*<|(?<=[^\S\n])#)|[^\S\n]*(?:\n|[\'"](?=[^\S\n]|$|[;&|)\n])))|(?<![\w-])echo[^\S\n]+\\?(?-i:declare|typeset)(?:[^\S\n]+(?:-(?![a-zA-Z]*[fF])[a-zA-Z]+|\+[a-zA-Z]+|--print|--))*(?:[^\S\n]*(?:\|(?!\|)|\)|`)|(?:(?<=\s[-+][a-zA-Z])|(?<=\s[-+][a-zA-Z]{2})|(?<=\s[-+][a-zA-Z]{3})|(?<=--print)|(?<=\s--))[^\S\n]*[0-9&]*>)|(?:(?<=\s-c [\'"])|(?<=-[a-z]c [\'"])|(?<=\seval [\'"])|(?<=\sexec [\'"])|(?<=^eval [\'"]))\\?(?-i:declare|typeset)(?:[^\S\n]+(?:-(?![a-zA-Z]*[fF])[a-zA-Z]+|\+[a-zA-Z]+|--print|--))*(?:[\'"](?=[^\S\n]|$|[;&|)\n])|[^\S\n]*(?:$|;|&|\||\)|`|[0-9]*>[^\S\n]*\S|[0-9]*<|(?<=[^\S\n])#))|(?:\$\(|`)(?:(?!\$\(|(?<![\w-])(?:echo|printf)[^\S\n])[^)`\n])*(?<![\w-])(?:echo|printf)[^\S\n]+[\'"]?\\?(?-i:declare|typeset)(?:[^\S\n]+(?:-(?![a-zA-Z]*[fF])[a-zA-Z]+|\+[a-zA-Z]+|--print|--))*[\'"]?[^\S\n]*(?:\)|`|;|&|\|)
action: block
mask_data: true
---

🚫 **Blocked: Dumping variables with `declare`**

**What was blocked:** `declare`, `typeset`, `readonly` or `declare -p`/`-x` with no variable names, or `declare -p $(compgen -v)` (prints all variables with their values)

**Why:** This dumps ALL shell variables including secrets, tokens, and credentials.

**Safe alternatives:**

- List variable names only: `compgen -v`
- Check if variable exists: `[ -n "$VAR" ] && echo "set"`
- Check variable type: `declare -p VARNAME 2>/dev/null | cut -d= -f1`

**Note:** `declare -x VAR=1`, `declare -i VAR=1`, `declare -a ARR`, `declare -f`, `readonly VAR=1` and other uses that name a variable are allowed.

**False positive?** Open an issue: `gh issue create --repo anthony-spruyt/claude-plugins --title "False positive: block-declare-dump" --label bug` and describe the blocked command in the body using `--body-file` to avoid re-triggering hooks.
