---
name: block-message-secrets
enabled: true
event: bash
# $(...) is skipped: the parser keeps its source text, and the commands inside get their own lines
# Fallback starts each piece once, taking its first gh/git subcommand in a lookahead (atomic): retrying later ones is cubic
conditions:
  - field: command
    operator: command_match
    pattern: '^(?:gh(?: -\S+(?: (?:''[^'']*''|[^-\s''])(?:''[^'']*''|[^\s''])*)?)* (?:issue|pr|release|gist) |git(?: -\S+(?: (?:''[^'']*''|[^-\s''])(?:''[^'']*''|[^\s''])*)?)* (?:commit|tag|notes)\b)(?:[^$\\]|\\.|\$(?!\()|\$\((?:[^()]|\([^()]*\))*\))*?\$\{?[A-Za-z0-9_]*(?:_PAT|TOKENS?|SECRETS?|PASSWORD|PASSWD|_PASS|_PWD|PASSPHRASE|CREDENTIALS?|PRIVATE_KEY|API_?KEY|SECRET_KEY|ACCESS_KEY|_KEY|_AUTH)[0-9]*\b(?!:?\+)'
    fallback: '(?:^|(?<=[\n;&|]))(?:(?=((?=([^\n;&|]*?\bgh\s))\2(?:[^\n;&|]*?\s)??(?:issue|pr|release|gist)\b))\1|(?=((?=([^\n;&|]*?\bgit\s))\4(?:[^\n;&|]*?\s)??(?:commit|tag|notes)\b))\3)[^\n;&|$]*(?:\$(?!\{?[A-Za-z0-9_]*(?:_PAT|TOKENS?|SECRETS?|PASSWORD|PASSWD|_PASS|_PWD|PASSPHRASE|CREDENTIALS?|PRIVATE_KEY|API_?KEY|SECRET_KEY|ACCESS_KEY|_KEY|_AUTH)[0-9]*\b(?!:?\+))[^\n;&|$]*)*\$\{?[A-Za-z0-9_]*(?:_PAT|TOKENS?|SECRETS?|PASSWORD|PASSWD|_PASS|_PWD|PASSPHRASE|CREDENTIALS?|PRIVATE_KEY|API_?KEY|SECRET_KEY|ACCESS_KEY|_KEY|_AUTH)[0-9]*\b(?!:?\+)'
action: block
---

🚫 **Blocked: Secret variable in a commit, issue or PR message**

**What was blocked:** A `gh issue`/`gh pr`/`gh release`/`gh gist` or `git commit`/`git tag`/`git notes` command where a secret-looking variable (`$GITHUB_TOKEN`, `${API_KEY}`, ...) expands into the text.

**Why:** The shell puts the real value into the message. Commits, issues and PRs are public and hard to scrub.

**Still allowed:**

- The name as plain text in single quotes: `git commit -m 'docs: never echo $GITHUB_TOKEN'`
- Set checks that print fixed text: `"${GITHUB_TOKEN:+token set}"`
- `gh secret set NAME --body "$NAME"`, which stores the value, not publishes it

**False positive?** Open an issue: `gh issue create --repo anthony-spruyt/claude-plugins --title "False positive: block-message-secrets" --label bug` and describe the blocked command in the body using `--body-file` to avoid re-triggering hooks.
