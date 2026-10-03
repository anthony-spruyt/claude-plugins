---
name: block-gh-auth-token
enabled: true
event: bash
conditions:
  - field: command
    operator: command_match
    pattern: '^gh(?: (?!\|)\S+)* auth (?:token\b|status(?: (?!\|)\S+)* (?:--show-token|-[a-zA-Z]*t[a-zA-Z]*)(?: |$))'
    fallback: '\bgh\s+auth\s+(?:token\b|status\b[^\n;&|]*\s(?:--show-token|-[a-zA-Z]*t))'
action: block
mask_data: true
---

🚫 **Blocked: Printing the GitHub CLI token**

**What was blocked:** `gh auth token` or `gh auth status --show-token` / `-t`, which print the GitHub token.

**Why:** The token grants the user's GitHub access. Once printed it is in the conversation.

**Instead:**

- Check login state: `gh auth status`
- Call the API through gh, which sends the token for you: `gh api user`
- Pipe it straight into a tool without printing it: ask the user to run that command themselves

**False positive?** Open an issue: `gh issue create --repo anthony-spruyt/claude-plugins --title "False positive: block-gh-auth-token" --label bug` and describe the blocked command in the body using `--body-file` to avoid re-triggering hooks.
