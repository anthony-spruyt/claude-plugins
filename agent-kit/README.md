# agent-kit

Progress notes that survive compaction for the main session and builder subagents, with a warning before compaction, helper scripts on the Bash `PATH`, and the `writing-agents` skill.

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

| Who               | Notes                                                   | Bookkeeping                                                                            |
| ----------------- | ------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| Main session      | `<session_id>.md` in the checkout cwd is in (see below) | `<session_id>.state`, `<session_id>.claim-<n>`                                         |
| Opted-in subagent | `agent-<agent_id>.md`, always in the project folder     | `agent-<agent_id>.state`, `agent-<agent_id>.claim-<n>`, `agent-<agent_id>.claim-nudge` |

The main session's notes path is resolved once at session start (the worktree root when cwd is in a worktree of the project, otherwise the project; notes already written in the project checkout win when cwd's checkout has none) and saved in the `.state` file. A leading `agent-` on `agent_id` is stripped. Ids must match `^[A-Za-z0-9_-]+$`.

### Config

The plugin default is `config/progress.json`:

```json
{ "notesAgents": ["builder"], "nudgeAfterToolCalls": 10, "compactAtTokens": 200000, "warnAtPercent": [90, 95] }
```

A repo overrides it in `$CLAUDE_PROJECT_DIR/.claude/agent-kit.json`, with the same keys nested under `progress`:

```json
{ "progress": { "notesAgents": ["builder", "agent-kit:reviewer"], "nudgeAfterToolCalls": 15, "compactAtTokens": 160000 } }
```

| Key                   | Meaning                                                                            | Valid values                |
| --------------------- | ---------------------------------------------------------------------------------- | --------------------------- |
| `notesAgents`         | `agent_type` values that keep notes (exact match); every other subagent is ignored | Array of non-empty strings  |
| `nudgeAfterToolCalls` | Tool calls an opted-in subagent may make before it is reminded to start notes      | Integer from 1 to 999999    |
| `compactAtTokens`     | Context size, in tokens, at which this setup auto-compacts                         | Integer from 1 to 999999999 |
| `warnAtPercent`       | Percentages of `compactAtTokens` that trigger a warning; `[]` turns warnings off   | Array of integers 1 to 100  |

- **Merge:** shallow, per key. A key the repo sets replaces the default key; arrays replace, they do not merge. Keys the repo leaves out keep the default.
- **Fallback:** each key resolves on its own: the repo value if valid, else the plugin default value if valid, else the built-in (`["builder"]`, 10, 200000 and `[90, 95]`). A value of the wrong type or out of range is not valid; `15.0` and `1e1` count as integers. A repo file that is missing, unparseable, or has a `"progress"` that is not an object means the defaults, as does a broken plugin
  default.
- **Safety:** the repo file is untrusted input. It is read only if it is a regular file, not a symlink and not under a symlinked `.claude` folder, and only its first 64 KiB. The plugin default must be a regular file (a symlink to one is fine) and is also read up to 64 KiB. Any error means no output and exit 0.
- **Cost:** a hook reads both files at most once per invocation, in one `jq` call. The main session reads them only on `PreToolUse`.

### Events

| Event                                  | Who                     | Action                                                                                                                        |
| -------------------------------------- | ----------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| SessionStart startup/resume/clear/fork | main                    | Resolve and save the notes path; inject path, rule and existing notes; save the transcript's compaction count                 |
| SessionStart compact                   | anyone                  | Nothing (not even wired), see below                                                                                           |
| SubagentStart (also on resume)         | opted-in subagent       | Inject path, rule and existing notes; save its transcript's compaction count                                                  |
| PreToolUse                             | main, opted-in subagent | If the `compact_boundary` count is above the saved one: claim it, inject path, rule and notes. No saved state: start as above |
| PreToolUse (no compaction to report)   | main, opted-in subagent | If the context has crossed a `warnAtPercent` level: claim `.claim-warn-<level>`, inject the warning (see below)               |
| PreToolUse (nothing above to report)   | opted-in subagent       | If its notes are missing and it has made `nudgeAfterToolCalls` tool calls: claim `.claim-nudge`, inject the reminder          |
| SubagentStop                           | opted-in subagent       | Delete its `.state` and `.claim-*`, never its notes                                                                           |
| SessionEnd                             | main                    | Delete the session's `.state` and `.claim-*`, never its notes                                                                 |

### Compaction

Claude Code fires `SessionStart(compact)` with the main session's payload even when a subagent compacted ([anthropics/claude-code#91910](https://github.com/anthropics/claude-code/issues/91910)). It can't say who to answer, so it stays silent. Every conversation that keeps notes gets them on its first tool call after compaction, through `PreToolUse`. A reply with no tool call in between runs
without them. Parallel tool calls race for the injection with an exclusive-create claim file, so it happens once. Winning a claim deletes that key's older numbered claims, so at most one `.claim-<n>` stays per key (the sweep leaves `.claim-nudge` alone: it is dropped at start and at stop).

### Notes reminder

The start message lands ahead of the agent's brief, and many subagents never write notes. On `PreToolUse`, an opted-in subagent whose notes file is missing (or empty) gets one reminder once its own transcript holds enough `tool_use` entries. The first `PreToolUse` that finds usable notes takes the claim without a message, so deleting the notes later (as the rule says to when the task is done)
never triggers the reminder. The reminder says how many tool calls it is in, gives the exact notes path and repeats the rule. An exclusive-create claim file, `agent-<agent_id>.claim-nudge`, makes it fire once per subagent, even with parallel tool calls; `SubagentStop` and the next start drop the claim. The main session is unchanged.

The threshold is `nudgeAfterToolCalls` (see Config); the default is 10.

### Context warning

No hook fires near the context limit, and `PreCompact` output never reaches the agent. So `PreToolUse` measures the context itself. It reads the latest assistant entry among the last 200 lines of the conversation's own transcript, after its last `compact_boundary`, and adds `input_tokens`, `cache_creation_input_tokens` and `cache_read_input_tokens`. `<synthetic>` and malformed entries are skipped,
and so are side-chain entries in the main transcript (a subagent's own transcript marks every entry side-chain); with no usable entry it stays silent. When that size reaches a `warnAtPercent` level of `compactAtTokens`, the agent is told the size and the percentage, and to bring its notes up to date now. The warning carries the notes path and the rule, but not the notes text, because the context
is nearly full.

- Set `compactAtTokens` to where your setup compacts. A `compact_boundary` entry's `compactMetadata.preTokens` in a transcript shows it. It is one value per repo, so a session with a larger context window than that is warned early.
- Each level fires once per compaction cycle, through an exclusive-create `.claim-warn-<level>`. A jump past several levels gives one warning, for the highest.
- Reporting a compaction drops the key's `.claim-warn-*`, so the levels fire again in the next cycle. A session start or subagent start, resume included, drops them too. A reply that reports a compaction gives no warning, and a warning delays the notes reminder to the next call.
- The check runs only on tool calls. A single large tool result can jump past a level and the compaction point before the next check, so leave headroom.

### Safety

The script never blocks a tool call or session start: a missing `jq`, bad input, a symlinked folder or file, or any error means no output and exit 0. Total injected text is capped at 9,500 characters, under Claude Code's 10,000-character hook output cap; longer notes are cut with a marker naming the file.

## Scripts on PATH

The plugin's `bin/` is on the Bash tool's `PATH` in the main session and in subagents, after the user's own `PATH`. Call them by bare name.

| Script             | Purpose                                                                             |
| ------------------ | ----------------------------------------------------------------------------------- |
| `workspace.sh`     | Clone a repo into its own directory on a new branch and print the path              |
| `push-reviewed.sh` | Push the signed commits a reviewer approved, or stop without pushing                |
| `ci-status.sh`     | Report CI, CodeQL, Sonar and pending review of a PR or commit, optionally waiting   |

## Skills

`writing-agents`: patterns for writing and trimming agent system prompts, including a section on plugin agents.

## Tests

```bash
bats tests/agent-kit/
```
