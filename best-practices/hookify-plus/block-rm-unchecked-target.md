---
name: block-rm-unchecked-target
enabled: true
event: bash
tool_matcher: Bash
# regex_match reads the raw command: command_match would expand a glob to the files in the working directory
conditions:
  - field: command
    operator: command_match
    pattern: '^(?:rm|rmdir)(?:\s|$)'
    fallback: '^(?!.*<<)(?:.*[\s;&|(){}`\x27\"])?(?:rm|rmdir)(?:\s|$)'
  - field: command
    operator: regex_match
    pattern: '(?<![\w.$-])(?:rm|rmdir)(?:(?:[^\S\n]|\\\n)+(?![^\s;&|]*?(?<![\w.$-])(?:rm|rmdir)(?=[\s;&|)\x27\"`\\]|$))[^\s;&|]+)*?(?:[^\S\n]|\\\n)+(?:(?:\*/?(?=[\x27\"]*(?:[\s;&|)`]|$)))|(?:(?![^\s;&|]*\$\{[^}$]*:\?)(?:[^\s;&|\"\x27]|\"[^\"\n;&|]*\"|\x27[^\x27\n;&|]*\x27)*/\*/?(?=[\x27\"]*(?:[\s;&|)`]|$)))|(?:[\\\"\x27]*\$(?:\w+|[@*#]|\{[^}:?$]*\})[\\\"\x27]*/(?=[\x27\"]*(?:[\s;&|)`]|$)))|(?:[\\\"\x27]*(?:/+(?:[^/\s;&|*?$`\"\x27\\]+/*)?|(?:~|\$HOME|\$\{HOME\})(?:[\\\"\x27]*/+)?)(?=[\x27\"]*(?:[\s;&|)`]|$)))|(?:[^\s;&|]*/[\\\"\x27]*(?:\$\((?:[^()]|\([^()]*\))*\)|`[^`]*`)(?=[\x27\"]*(?:[\s;&|)`]|$))))|(?<![\w.$-])rm(?=(?:(?:[^\S\n]|\\\n)+(?![^\s;&|]*?(?<![\w.$-])(?:rm|rmdir)(?=[\s;&|)\x27\"`\\]|$))[^\s;&|]+)*?(?:[^\S\n]|\\\n)+-(?:-recursive|(?=[a-z]*r)[a-z]*)(?=[^\S\n]|$))(?:(?:[^\S\n]|\\\n)+(?![^\s;&|]*?(?<![\w.$-])(?:rm|rmdir)(?=[\s;&|)\x27\"`\\]|$))[^\s;&|]+)*?(?:[^\S\n]|\\\n)+[\\\"\x27]*(?:\$\((?:[^()]|\([^()]*\))*\)|`[^`]*`)(?=[\x27\"]*(?:[\s;&|)`]|$))'
action: block
mask_data: true
---

🚫 **Blocked: `rm` target Claude Code stops on**

**What was blocked:** An `rm` or `rmdir` whose target is a glob (`*`, `dir/*`), a variable under a glob or trailing slash (`"$DIR"/*`), nothing but a command substitution, a path ending in one (`~/$(cmd)`), or the filesystem root, `~`, `$HOME` or a top-level directory such as `/tmp`.

**Why:** Claude Code cannot check these targets, so it stops and asks the owner even in bypass mode, and waits 2 minutes before denying.

**Instead:**

- Name every target as a literal path: `rm -rf /abs/dir/old1 /abs/dir/old2`
- To empty a directory: `rm -rf /abs/dir && mkdir -p /abs/dir`
- With a variable: guard it, `rm -rf "${DIR:?}"/*`, or use the literal path
- With a command's output: run the command first, then remove the literal paths it printed

**False positive?** Open an issue: `gh issue create --repo anthony-spruyt/claude-plugins --title "False positive: block-rm-unchecked-target" --label bug` and describe the blocked command in the body using `--body-file` to avoid re-triggering hooks.
