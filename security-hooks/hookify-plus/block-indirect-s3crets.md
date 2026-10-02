---
name: block-indirect-secrets
enabled: true
event: bash
# A computed name can be glued from parts (a=GITHUB_; b=TOKEN), so only a plain literal nameref target is checkable
# ${!arr[@]} and ${!prefix*} list names, not values, so they stay allowed
conditions:
  - field: command
    operator: regex_match
    pattern: '\$\{!(?![A-Za-z_]\w*(?:\[[@*]\]|[@*])\})|\$\{[^}\s]*@P\}|(?<![\w-])(?:declare|typeset|local)(?:\s+[-+][A-Za-z]+)*\s+-[A-Za-z]*n[A-Za-z]*(?!(?:\s+[-+][A-Za-z]+)*(?:\s+[A-Za-z_]\w*=(?![A-Za-z0-9_]*(?:_PAT|TOKENS?|SECRETS?|PASSWORD|PASSWD|_PASS|_PWD|PASSPHRASE|CREDENTIALS?|PRIVATE_KEY|API_?KEY|SECRET_KEY|ACCESS_KEY|_KEY|_AUTH)[0-9]*(?![A-Za-z0-9_]))[A-Za-z_]\w*)+[^\S\n]*(?:[;&|)\n]|$))'
action: block
mask_data: true
---

🚫 **Blocked: Reading a variable by a computed name**

**What was blocked:** `${!x}`, `${x@P}`, or a nameref (`declare -n`, `local -n`, `typeset -n`) whose target is not a plain, non-secret name.

**Why:** `x=GITHUB_TOKEN; echo "${!x}"` prints the token. The echo and heredoc rules only see `$x`, and the name can be glued from parts (`a=GITHUB_; b=TOKEN; x=$a$b`), so no rule can tell it is a secret.

**Still allowed:**

- A nameref to a plain name: `declare -n r=items`
- Listing names, not values: `${!MY_MAP[@]}` (array keys) and `${!GITHUB*}` (variable names)

**If you need to check a secret is set:**

```bash
[ -n "$VAR_NAME" ] && echo "set" || echo "not set"
```

**False positive?** Open an issue: `gh issue create --repo anthony-spruyt/claude-plugins --title "False positive: block-indirect-secrets" --label bug` and describe the blocked command in the body using `--body-file` to avoid re-triggering hooks.
