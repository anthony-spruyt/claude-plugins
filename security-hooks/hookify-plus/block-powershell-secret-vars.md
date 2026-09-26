---
name: block-powershell-secret-vars
enabled: true
event: bash
tool_matcher: PowerShell
pattern: (\$env:|\$\{env:|GetEnvironmentVariable\(\s*['"])[A-Za-z_]*(_PAT|TOKEN|SECRET|PASSWORD|PASSPHRASE|CREDENTIAL|PRIVATE_KEY|API_KEY|SECRET_KEY|ACCESS_KEY)\b
action: block
---

🚫 **Blocked: Reading a sensitive environment variable in PowerShell**

**What was blocked:** `$env:NAME` or `[Environment]::GetEnvironmentVariable('NAME')` where the name looks like a secret (PAT, TOKEN, SECRET, PASSWORD, KEY, CREDENTIAL)

**Why:** This would expose the secret value in the output.

**If you need to know whether it is set:**

- Check existence only: `Test-Path Env:VARIABLE_NAME`
- Ask the user: "Is `$env:VARIABLE_NAME` set?"

**False positive?** Open an issue: `gh issue create --repo anthony-spruyt/claude-plugins --title "False positive: block-powershell-secret-vars" --label bug` and describe the blocked command in the body using `--body-file` to avoid re-triggering hooks.
