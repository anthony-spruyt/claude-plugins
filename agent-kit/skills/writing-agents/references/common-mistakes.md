# Common Mistakes

| Mistake                                                 | Fix                                                                                                                                |
| ------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| Workflow summary in description                         | Brief capability + triggering conditions only. Put workflow in body                                                                |
| CRITICAL/MANDATORY/NEVER overuse                        | Normal language. Current models overtrigger on aggressive emphasis                                                                 |
| Explaining Kubernetes/YAML/Git basics                   | Remove. The model knows these                                                                                                      |
| Copying CLAUDE.md secret rules                          | Remove. Agent inherits project rules                                                                                               |
| Padding in a long system prompt                         | Remove what the model already knows and inherited context; keep environment facts and reasons                                      |
| All tools inherited                                     | Restrict to what's needed (least privilege)                                                                                        |
| No output format specified                              | Add structured output template                                                                                                     |
| Example dialogue in description                         | Replace with intent categories under "When to use" / "When NOT to use"                                                             |
| Magic commands without explanation                      | Add brief comment explaining why (right altitude)                                                                                  |
| No feedback on the agent's own prompt                   | Add an `## Agent Definition Feedback` section (see SKILL.md System Prompt Structure item 9)                                        |
| Agent spawns subagents for lookups                      | Say when not to delegate: lookups a direct Bash search or Read can answer stay in the agent (`references/anthropic-best-practices.md` Section 8) |
| Multi-goal agent                                        | Split into focused agents. One clear goal, input, output per agent                                                                 |
| No confirmation gates for destructive actions           | Add explicit guidance on which actions need user confirmation                                                                      |
| Independent checks run sequentially                     | Mark parallel groups: "Run in parallel: [list]. After those pass: [list]" (see `references/anthropic-best-practices.md` Section 6) |
| No feedback loop for validation agents                  | Add validator -> fix -> retry pattern with structured output (file paths, line numbers, exact fixes)                               |
| Sequential workflow with no halt conditions             | Add "stop on error" at each step. Do not proceed if intermediate step fails                                                        |
| Dropping `tools` field during optimization              | Verify all frontmatter fields survived. Missing `tools` silently grants all tools                                                  |
| Description exceeds 1024 chars                          | Remove example dialogue and workflow summary; fold near-synonymous triggers into one category                                      |
| Replacing exact commands with prose during optimization | Keep domain-specific commands with non-obvious flags. Prose like "then commit" loses precision vs exact `git commit -m "..."`      |
| Cutting behavioral anchor commands                      | Commands with specific flags (`--sort-by`, `-l app.kubernetes.io/name=`) guide behavior — not "basics Opus knows"                  |
| No effectiveness check after optimization               | Compare original vs optimized for lost domain-specific content not covered by inherited context                                    |
