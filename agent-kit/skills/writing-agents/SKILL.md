---
name: writing-agents
description: Use when creating new agents, editing existing agent system prompts, optimizing agent token efficiency, or maintaining agent quality. Applies when agent is too long, not performing well, overtriggering, or when reviewing agent files in .claude/agents/. Does not apply to skills, hooks, commands, or slash commands.
---

# Writing Agents

## Overview

Patterns and workflows for writing effective, token-efficient agent system prompts.

## Quick Reference

| Task                   | Reference                                          |
| ---------------------- | -------------------------------------------------- |
| Frontmatter fields     | `references/agent-frontmatter.md`                  |
| Override built-in      | `references/agent-frontmatter.md`, Overriding built-in agents |
| Plugin agents          | `references/agent-frontmatter.md`, Plugin agents   |
| Description template   | `references/project-patterns.md` Section 6         |
| Model selection        | `references/project-patterns.md` Section 2         |
| Size targets           | `references/project-patterns.md` Section 3         |
| Output format patterns | `references/project-patterns.md` Section 4         |
| Handoff patterns       | `references/project-patterns.md` Section 5         |
| Emphasis calibration   | `references/anthropic-best-practices.md` Section 3 |
| Parallel execution     | `references/anthropic-best-practices.md` Section 6 |
| Common mistakes        | `references/common-mistakes.md`                    |

## Description Field

**Syntax:** Single line with `\n` for newlines. Wrap in `'...'` if contains `#` after whitespace.

**Write in third person** — the description is injected into the system prompt by the routing system.

**Content pattern:** Brief capability statement (1 clause), then triggering conditions. Don't expand the capability statement into a workflow summary: the description rides in every parent request and is all the parent sees when deciding to delegate, while the body loads only when the agent runs. Keep "what" to a single clause, put process details in the body.

**Include:**

- "When to use" conditions, written as categories of intent rather than sample phrasings
- "When NOT to use" boundaries, naming the agent or command to use instead

Leave `<example>` dialogue out of the description. The parent reads it on every request as routing signal, and sample exchanges anchor delegation to the phrasings they show; the intent categories carry the same signal. Worked examples the agent itself needs go in the body.

See `references/project-patterns.md` Section 6 for the template.

## System Prompt Structure

Canonical section order for this project:

1. **Persona/Role** — Expert identity with domain expertise, 1-2 sentences
2. **Core Responsibilities** — Numbered, 3-5 items
3. **Mandatory Gates** — Issue requirements, input validation
4. **Classification/Detection** — Change-type analysis, input categorization
5. **Workflow Steps** — The main process
6. **Output Format** — Structured template (verdict header, evidence, next steps)
7. **Handoff Protocol** — How results return to caller
8. **Rules** — Constraints the model would otherwise get wrong, each with its reason
9. **Agent Definition Feedback** — The agent ends its final reply to the caller with an `### Agent Definition Feedback` section: each problem as `- [definition] <what happened> → <change to its own file>`, `- [rules] <what happened> → <change to CLAUDE.md, .claude/rules/<file> or the hook>` or `- [brief] <what happened> → <what the caller's brief should have said>`. Tag `[definition]` if it would recur under any reasonable brief and comes from the agent file; `[rules]` if it comes from `CLAUDE.md`, `.claude/rules/` or a hook; otherwise `[brief]`. Suggest only; never self-edit. Copy the wording from an existing agent. Don't use `memory`: settings disable auto memory. Skip it when a machine parses the output (renovate-pr-analyzer feeds n8n)

Not every agent needs all sections. Small focused agents may only need Persona, Workflow, Rules, and Output Format.

**Output format:** Agents feeding orchestrators use rigid parseable formats. Standalone agents use human-readable reports. See `references/project-patterns.md` Section 4.

**Handoff patterns:** Choose from: GitHub issue comment, structured return to caller, terminal states (SUCCESS/ROLLBACK/PARTIAL), or fix-and-retry loop. See `references/project-patterns.md` Section 5.

## Creation Workflow

Write the agent in the main session. Use one fresh-context sub-agent for review, so the reviewer isn't anchored on drafting choices.

### Phase 1: Create

Read the agent requirements, this skill, existing agents (for pattern reference), and all inherited context files (CLAUDE.md, `.claude/rules/*`). Then:

1. **Discover patterns** — Read 2-3 existing agents in `.claude/agents/` for local conventions
2. **Define persona** — Expert identity with domain expertise, 1-2 sentences
3. **Write frontmatter** — Description complying with the Description Field section of this skill (under 1024 chars, no workflow summary, no `<example>` dialogue, "When to use" and "When NOT to use" sections). Choose model, effort, and tools (model and effort — `references/project-patterns.md` Section 2; least privilege — `references/anthropic-best-practices.md` Section 9)
4. **Structure system prompt** — Follow section order from System Prompt Structure above. Include output format template and handoff protocol
5. **Calibrate freedom** — High freedom for judgment calls, low freedom for exact commands (see `references/anthropic-best-practices.md` Section 2)
6. **Scope-limit** — If testing shows over-reach, add "Only make changes directly requested." (see `references/anthropic-best-practices.md` Section 4)
7. **Safety gates** — Identify destructive or externally-visible operations. Add confirmation gates for irreversible actions. For hard-stop gates, state the stop unconditionally with its reason and a named end state (e.g., "stop and return BLOCKED: <reason>"). Add "stop on error" for sequential workflows
8. **Calibrate emphasis** — Same rules as Optimization Phase 1 step 4
9. **Avoid inherited duplication** — Read CLAUDE.md and `.claude/rules/*`. Do not duplicate content. Use single-line references (e.g., "Follow inherited secret handling rules")
10. **Size check** — Run `wc -l` and `wc -w`. Past ~300 lines / 2,000 words, re-test each section against `references/anthropic-best-practices.md` Section 1; length alone is not a reason to cut

### Phase 2: Review (one sub-agent)

Dispatch one fresh sub-agent with the new file, this skill, and the inherited context files. It checks:

- **Structure**: frontmatter fields, description under 1024 chars, no workflow summary, no `<example>` dialogue, emphasis calibrated, output format and handoff protocol present.
- **Completeness**: The System Prompt Structure sections this agent needs are present (at minimum: Persona, Workflow, Rules, Output Format). No inherited context duplicated. No explanations of what the model already knows. Domain-specific commands have non-obvious flags where needed.

It returns PASS/FAIL with specific issues and exact fixes.

### Phase 3: Fix

Apply the fixes in the main session. Re-run Phase 2 only when a fix changed behavior (workflow, gates, tools), not for wording.

## Optimization Workflow

Optimize in the main session. Use one fresh-context sub-agent for review, so the reviewer has no sunk cost in the cuts.

### Phase 1: Optimize

Read the agent file, this skill, and all inherited context files (CLAUDE.md, `.claude/rules/*`). Then:

1. **Measure** — Count lines (`wc -l`) and words (`wc -w`). Identify largest sections
2. **Fix description field** — Must comply with the Description Field section of this skill:
   - Under 1024 chars (measure and verify). If over: remove workflow summaries and fold near-synonymous triggers into one category
   - No workflow summary (lines like "Handoff flow: X → Y → Z"). Only capability + triggering conditions
   - No `<example>` dialogue. Move any trigger an example carried that the conditions don't already cover into "When to use" or "When NOT to use", then delete the example
   - Must have "When to use" and "When NOT to use" sections
3. **Remove inherited context** — Read CLAUDE.md and every `.claude/rules/` file. Search the agent for duplicated content. Common: secret handling, git staging, research priority, domain substitution. Replace with single-line references (e.g., "Follow inherited secret handling rules")
4. **Calibrate emphasis** — Soften CRITICAL/MUST/NEVER/FORBIDDEN/MANDATORY (see `references/anthropic-best-practices.md` Section 3). Remove explanations the model already knows (Section 12). **Safety gates** (hard stops preventing data loss, secret exposure, skipping required inputs) stay unconditional, stated plainly with their reason. **Operational preferences** (tool choice, workflow ordering, style) use normal language — no bold, no
   CRITICAL, no blockquote emphasis
5. **Cut what fails the test** — Remove what the model already knows, inherited context, and verbose examples (`references/anthropic-best-practices.md` Section 1). Agents are single files; do not extract. **Keep:** domain-specific commands with non-obvious flags, exact commit/git commands, behavioral anchors preventing shallow execution
6. **Verify frontmatter** — All original fields must survive (`name`, `description`, `model`, `effort`, `tools`). Missing `tools` silently grants all tools

### Phase 2: Review (one sub-agent)

Dispatch one fresh sub-agent (no shared context with the optimizer). It reads the optimized file, the original (via `git show <pre-optimization-ref>:<path>`), inherited context files, and this skill, and checks:

- **Structure**: Frontmatter fields survived. Description under 1024 chars, no workflow summary, no `<example>` dialogue. System prompt sections present. Emphasis calibrated (safety gates unconditional with reasons). Output format and handoff protocol present.
- **Effectiveness**: Lost domain-specific knowledge not in inherited context and that the model wouldn't know. All workflow steps still represented. Domain commands with non-obvious flags preserved. Each cut classified SAFE/RISKY/LOST.

It returns PASS/FAIL plus EFFECTIVE/DEGRADED/BROKEN, with specific issues and exact fixes.

### Phase 3: Fix

Apply the fixes in the main session. Re-run Phase 2 only when a fix restored or changed behavior, not for wording.

## Common Mistakes

| Mistake                          | Fix                                                                 |
| -------------------------------- | ------------------------------------------------------------------- |
| Workflow summary in description  | Brief capability + triggering conditions only. Put workflow in body |
| CRITICAL/MANDATORY/NEVER overuse | Normal language. Current models overtrigger on aggressive emphasis |
| Padding in a long system prompt  | Remove what the model already knows; keep facts and reasons          |
| No output format specified       | Add structured output template                                      |
| Example dialogue in description  | Replace with intent categories under "When to use" / "When NOT to use" |
| See full list                    | `references/common-mistakes.md`                                     |
