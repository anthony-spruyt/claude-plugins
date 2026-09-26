---
name: block-read-proc-environ
enabled: true
event: all
action: block
conditions:
  - field: file_path
    operator: regex_match
    pattern: ^/proc/(self|\$\$|[0-9]+|thread-self)/(task/[0-9]+/)?environ$
---

🚫 **Blocked: Reading process environment from /proc**

**What was blocked:** Opening `/proc/self/environ` or `/proc/[pid]/environ` with a file tool

**Why:** These files contain ALL environment variables for a process, which may include secrets.

**If you need a specific variable:**

1. Ask the user: "What is the value of $VARIABLE_NAME?"
2. User can provide the value if it's safe
3. User can decline if it contains secrets

**False positive?** Open an issue: `gh issue create --repo anthony-spruyt/claude-plugins --title "False positive: block-read-proc-environ" --label bug` and describe the blocked command in the body using `--body-file` to avoid re-triggering hooks.
