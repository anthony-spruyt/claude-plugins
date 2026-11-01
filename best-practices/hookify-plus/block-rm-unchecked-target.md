---
name: block-rm-unchecked-target
enabled: true
event: bash
tool_matcher: Bash|Monitor
# regex_match reads the raw command: command_match would expand a glob to the files in the working directory
conditions:
  - field: command
    operator: command_match
    pattern: '^(?:rm|rmdir)(?:\s|$)'
    fallback: '^(?!.*<<)(?:.*[\s;&|(){}`\x27\"])?(?:rm|rmdir)(?:\s|$)'
  - field: command
    operator: regex_match
    pattern: '(?:(?:^(?:(?!<<).)*?\n[^\S\n]*|(?:^|[;&|(){`])\s*)(?:[A-Za-z_]\w*=[^\s;&|(){}`\x27\"\\]*(?:[^\S\n]|\\\n)+){0,5}|(?<![\w.$-])(?:then|do|else|elif|if|while|until|time)\s+|(?<![\w.$-])(?:sudo|doas|env|command|builtin|exec|nohup|nice|ionice|timeout|stdbuf|setsid|flock|xargs|parallel|watch|-exec|-execdir|-ok|-okdir)(?:[^\S\n]|\\\n)+(?:[^\s;&|]+(?:[^\S\n]|\\\n)+){0,6}?|(?<![\w.$-])(?:-[a-z]*c|eval)(?:[^\S\n]|\\\n)+[\x27\"])(?:\\|/?(?:[\w.+-]+/)*)(?:(?:rm|rmdir)(?:(?:[^\S\n]|\\\n)+(?![^\s;&|]*?(?<![\w.$-])(?:rm|rmdir)(?=[\s;&|)\x27\"`\\]|$))[^\s;&|]+)*?(?:[^\S\n]|\\\n)+(?:(?:\*/?(?=[\x27\"]*(?:[\s;&|)`]|$)))|(?:(?![^\s;&|]*\$\{(?!(?:HOME|PWD|TMPDIR)[:}])[^}$]*:\?)(?:[^\s;&|\"\x27]|\"[^\"\n;&|]*\"|\x27[^\x27\n;&|]*\x27)*/\*/?(?=[\x27\"]*(?:[\s;&|)`]|$)))|(?:[\\\"\x27]*\$(?:\w+|[@*#]|\{[^}:?$]*\})[\\\"\x27]*/(?=[*?\[{$/\x27\"]|[\s;&|)`]|$))|(?:[\\\"\x27]*(?:/+(?:[^/\s;&|*?$`\"\x27\\]+/*)?|(?:~|\$HOME|\$\{HOME(?::[^}$]*)?\}|(?:\.\.?/+)*\.\.?)(?:[\\\"\x27]*/+)?)(?=[\x27\"]*(?:[\s;&|)`]|$)))|(?:[^\s;&|]*/[\\\"\x27]*(?:\$\((?:[^()]|\([^()]*\))*\)|`[^`]*`)(?=[\x27\"]*(?:[\s;&|)`]|$))))|rm(?=(?:(?:[^\S\n]|\\\n)+(?![^\s;&|]*?(?<![\w.$-])(?:rm|rmdir)(?=[\s;&|)\x27\"`\\]|$))[^\s;&|]+)*?(?:[^\S\n]|\\\n)+-(?:-recursive|(?=[a-z]*r)[a-z]*)(?=[^\S\n]|$))(?:(?:[^\S\n]|\\\n)+(?![^\s;&|]*?(?<![\w.$-])(?:rm|rmdir)(?=[\s;&|)\x27\"`\\]|$))[^\s;&|]+)*?(?:[^\S\n]|\\\n)+[\\\"\x27]*(?:\$\((?:[^()]|\([^()]*\))*\)|`[^`]*`)(?=[\x27\"]*(?:[\s;&|)`]|$)))'
action: block
mask_data: true
---

🚫 **Blocked: `rm` target Claude Code stops on**

**What was blocked:** An `rm` or `rmdir` whose target is a glob (`*`, `dir/*`), a variable followed by a glob, another variable or a trailing slash (`"$DIR"/*`, `"$DIR/$f"`), nothing but a command substitution, a path ending in one (`~/$(cmd)`), the working directory or a parent (`.`, `..`), or the filesystem root, `~`, `$HOME` or a top-level directory such as `/tmp`.

**Why:** Claude Code treats these as critical-path removals that nothing auto-approves, so even in bypass mode it stops to ask the user and denies after 2 minutes.

**Instead:**

- Name every target as a literal path: `rm -rf /abs/dir/old1 /abs/dir/old2`
- To empty a directory: `find /abs/dir -mindepth 1 -delete`
- With a variable: guard it, `rm -rf "${DIR:?}"/*` (not `$HOME`, `$PWD` or `$TMPDIR`: use a literal path)
- With a command's output: run the command first, then remove the literal paths it printed

**False positive?** Open an issue: `gh issue create --repo anthony-spruyt/claude-plugins --title "False positive: block-rm-unchecked-target" --label bug` and describe the blocked command in the body using `--body-file` to avoid re-triggering hooks.
