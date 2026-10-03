---
name: block-huge-glob
enabled: true
event: bash
conditions:
  - field: command
    operator: glob_overflow
action: block
---

🚫 **Blocked: Glob or brace that expands too far**

**What was blocked:** An unquoted glob or brace that would expand to more than 256 words or read more than 20,000 directory entries, such as `cat /proc/*/environ` on a busy machine or `echo {1..300}`.

**Why:** The security rules check every word bash would run. Past these limits they can't, and the output would flood the context anyway.

**Instead:**

- Narrow the glob: `ls src/*.ts`, not `ls src/*/*/*`
- Search with a tool: `rg pattern src/` or the Grep tool
- Count first: `find dir -maxdepth 1 | wc -l`
- Quote it if bash should not expand it: `echo '{1..300}'`

**False positive?** Open an issue: `gh issue create --repo anthony-spruyt/claude-plugins --title "False positive: block-huge-glob" --label bug` and describe the blocked command in the body using `--body-file` to avoid re-triggering hooks.
