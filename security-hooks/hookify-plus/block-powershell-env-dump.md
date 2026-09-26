---
name: block-powershell-env-dump
enabled: true
event: bash
tool_matcher: PowerShell
pattern: \b(Get-ChildItem|gci|dir|ls|Get-Item|gi)\s+(-Path\s+)?['"]?Env:(\\|/)?\*?['"]?(\s|$|\||;|\))|\[(System\.)?Environment\]::GetEnvironmentVariables\(
action: block
---

🚫 **Blocked: Dumping environment variables in PowerShell**

**What was blocked:** Listing the `Env:` drive (`Get-ChildItem Env:`, `gci env:`, `dir Env:`, `Get-Item Env:*`) or `[Environment]::GetEnvironmentVariables()`

**Why:** Environment variables often contain secrets, tokens, and credentials.

**If you need a specific variable:**

1. Ask the user: "What is the value of `$env:VARIABLE_NAME`?"
2. User can provide the value if it's safe to share

**Safe alternatives:**

- List variable names only: `Get-ChildItem Env: | Select-Object -ExpandProperty Name`
- Check if a variable exists: `Test-Path Env:VARIABLE_NAME`
- Get a specific non-secret var: `$env:PATH`

**False positive?** Open an issue: `gh issue create --repo anthony-spruyt/claude-plugins --title "False positive: block-powershell-env-dump" --label bug` and describe the blocked command in the body using `--body-file` to avoid re-triggering hooks.
