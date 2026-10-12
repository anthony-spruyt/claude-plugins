# agent-kit

Progress notes that survive compaction for the main session and builder subagents, helper scripts on the Bash `PATH`, and the `writing-agents` skill.

```bash
/plugin marketplace add anthony-spruyt/claude-plugins
/plugin install agent-kit@aspruyt-plugins
```

## Progress notes

Compaction loses detail, so multi-step work keeps its state on disk, as in Anthropic's [long-running agent harness](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents). One script, `scripts/progress.sh`, serves the main session and opted-in subagents. `git log` stays the source of truth.

### The rule

The rule text lives in the script and arrives with every injection (start, resume, after compaction):

- Keep notes for any task with more than one step. Skip one-shot edits and questions.
- Keep the file under 100 lines. First line: goal and issue. Then done with commit SHAs, the exact next step, decisions and why, dead ends, commands and gotchas.
- Update it after each commit and before stopping.
- Delete the file when the task is done. Keep it when blocked or unfinished.
- If a brief or the owner names an earlier notes file, read it first and delete it when finished.
- A new session or fork finds earlier notes with `ls -t` on the notes folder and picks the file whose goal matches.

### Where files live

Bookkeeping always lives in `$CLAUDE_PROJECT_DIR/.agent-progress/`, which the script creates with a `.gitignore` of `*`.

| Who               | Notes                                                   | Bookkeeping                                            |
| ----------------- | ------------------------------------------------------- | ------------------------------------------------------ |
| Main session      | `<session_id>.md` in the checkout cwd is in (see below) | `<session_id>.state`, `<session_id>.claim-<n>`         |
| Opted-in subagent | `agent-<agent_id>.md`, always in the project folder     | `agent-<agent_id>.state`, `agent-<agent_id>.claim-<n>` |

The main session's notes path is resolved once at session start (the worktree root when cwd is in a worktree of the project, otherwise the project; notes already written in the project checkout win when cwd's checkout has none) and saved in the `.state` file. A leading `agent-` on `agent_id` is stripped. Ids must match `^[A-Za-z0-9_-]+$`.

### Opt-in

A subagent keeps notes only if its `agent_type` is a line in `config/notes-agents` (exact match, `#` comments and blank lines ignored). It ships with `builder`. Every other subagent is ignored.

### Events

| Event                                  | Who                     | Action                                                                                                                        |
| -------------------------------------- | ----------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| SessionStart startup/resume/clear/fork | main                    | Resolve and save the notes path; inject path, rule and existing notes; save the transcript's compaction count                 |
| SessionStart compact                   | anyone                  | Nothing (not even wired), see below                                                                                           |
| SubagentStart (also on resume)         | opted-in subagent       | Inject path, rule and existing notes; save its transcript's compaction count                                                  |
| PreToolUse                             | main, opted-in subagent | If the `compact_boundary` count is above the saved one: claim it, inject path, rule and notes. No saved state: start as above |
| SubagentStop                           | opted-in subagent       | Delete its `.state` and `.claim-*`, never its notes                                                                           |
| SessionEnd                             | main                    | Delete the session's `.state` and `.claim-*`, never its notes                                                                 |

### Compaction

Claude Code fires `SessionStart(compact)` with the main session's payload even when a subagent compacted ([anthropics/claude-code#91910](https://github.com/anthropics/claude-code/issues/91910)).
It can't say who to answer, so it stays silent. Every conversation that keeps notes gets them on its first tool call after compaction, through `PreToolUse`. A reply with no tool call in between runs without them. Parallel tool calls race for the injection with an exclusive-create claim file, so it happens once.

### Safety

The script never blocks a tool call or session start: a missing `jq`, bad input, a symlinked folder or file, or any error means no output and exit 0. Total injected text is capped at 9,500 characters, under Claude Code's 10,000-character hook output cap; longer notes are cut with a marker naming the file.

### Handover from the old scripts

While `$CLAUDE_PROJECT_DIR/.claude/session-progress.sh` exists the plugin leaves the main session to it. While `$CLAUDE_PROJECT_DIR/.claude/scripts/builder-progress.sh` exists it leaves subagents to it. Delete those files and the plugin takes over on the next tool call.

## Scripts on PATH

The plugin's `bin/` is on the Bash tool's `PATH` in the main session and in subagents, after the user's own `PATH`. Call them by bare name.

| Script             | Purpose                                                                             |
| ------------------ | ----------------------------------------------------------------------------------- |
| `workspace.sh`     | Clone a repo into its own directory on a new branch and print the path              |
| `push-reviewed.sh` | Push the commits a reviewer approved, or stop without pushing                       |
| `ci-status.sh`     | Report the CI, CodeQL and Sonar status of a PR or commit, optionally waiting for it |

## Skills

`writing-agents`: patterns for writing and trimming agent system prompts, including a section on plugin agents.

## Tests

```bash
bats tests/agent-kit/
```
