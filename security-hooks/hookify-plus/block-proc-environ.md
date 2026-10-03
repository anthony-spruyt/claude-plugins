---
name: block-proc-environ
enabled: true
event: bash
conditions:
  - field: command
    operator: command_match
    pattern: '^(?!(?:echo|printf|git (?:grep|log)|gh search) ).*(?:^| |=|@)''?/+proc/+(?:[^\s''/]*/+){1,6}environ''?(?= |$)|(?-i:^ps(?: [aAcfghjlLmMnrsSTuvwxXZ]+)* [aAcfghjlLmMnrsSTuvwxXZ]*e[aAcfghjlLmMnrsSTuvwxXZ]*(?: |$))'
    fallback: '(?:^|[\s<=@''"])/+proc/+[^\s;&|]*/environ\b|(?-i:\bps(?:\s+[aAcfghjlLmMnrsSTuvwxXZ]+)*\s+[aAcfghjlLmMnrsSTuvwxXZ]*e[aAcfghjlLmMnrsSTuvwxXZ]*(?=\s|$))'
action: block
mask_data: true
---

🚫 **Blocked: Reading process environment from /proc**

**What was blocked:** Reading `/proc/self/environ`, `/proc/$$/environ`, or `/proc/[pid]/environ`, or `ps e` / `ps auxe`, which print the same thing

**Why:** These files contain ALL environment variables for a process, which may include secrets.

**If you need a specific variable:**

1. Ask the user: "What is the value of $VARIABLE_NAME?"
2. User can provide the value if it's safe
3. User can decline if it contains secrets

**Still allowed:** `ps aux`, `ps -ef` and other `ps` calls without the BSD `e` flag.

**False positive?** Open an issue: `gh issue create --repo anthony-spruyt/claude-plugins --title "False positive: block-proc-environ" --label bug` and describe the blocked command in the body using `--body-file` to avoid re-triggering hooks.
