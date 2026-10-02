---
name: warn-conventional-commits
enabled: true
event: bash
conditions:
  - field: command
    operator: command_match
    pattern: '^git(?: -\S+(?: (?:''[^'']*''|[^-\s''])(?:''[^'']*''|[^\s''])*)?)* commit(?: (?!\|)(?:''[^'']*''|[^\s''])+)* (?:-[a-zA-Z]*m |--message[= ]|''--message=)(?!''?(?:(?:feat|fix|chore|docs|style|refactor|perf|test|build|ci|revert)(?:\([^)]*\))?!?:|\$\())'
    fallback: 'git\s+commit\s+.*?-m\s+["''](?!(feat|fix|chore|docs|style|refactor|perf|test|build|ci|revert)[\(:])'
action: warn
warn_once: true
---

⚠️ **Reminder:** Use [Conventional Commits](https://www.conventionalcommits.org/) format: `<type>(<scope>): <description>`
