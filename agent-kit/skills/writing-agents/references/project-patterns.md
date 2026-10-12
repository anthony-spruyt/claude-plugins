# Patterns for Agent Authoring

Portable patterns for creating and optimizing Claude Code agents. Derived from Anthropic guidance and field observations.

## Contents

1. [Discover Existing Patterns](#1-discover-existing-patterns)
2. [Model Selection](#2-model-selection)
3. [Size Benchmarks](#3-size-benchmarks)
4. [Output Format Patterns](#4-output-format-patterns)
5. [Handoff Patterns](#5-handoff-patterns)
6. [Description Field Patterns](#6-description-field-patterns)

______________________________________________________________________

## 1. Discover Existing Patterns

Before creating or optimizing an agent, scan the project's agent directory:

1. List agents: `ls .claude/agents/`
2. Read 2-3 agents to understand local conventions
3. Note: model choices, tool restrictions, description structure, output format, size

This is more reliable than a static inventory that goes stale.

## 2. Model Selection

| Model      | When to Use                                                                                             |
| ---------- | ------------------------------------------------------------------------------------------------------- |
| **opus**   | Complex multi-step analysis, decision-making under uncertainty, machine-parseable output, orchestration |
| **sonnet** | Focused single-domain operations, lower token cost, pre-baked queries/templates                         |
| **haiku**  | Quick lookups, simple classification                                                                    |

Omitting `model` (or setting `inherit`) runs the agent on the main session's model.

**Effort.** Omit `effort` and the agent inherits the session's level. Set it when the agent needs a different depth: `medium` as the starting point for analysis and multi-step tool use, `low` for fixed checklists and pre-baked queries, `xhigh`/`max` only where a test showed a gain. On Sonnet, `low` makes skipping verification of a change more likely, so avoid it for agents that edit. Levels don't carry across models; re-check `effort` when you change `model`. Effort is the thinking control on current models: don't write "think step by step", "think harder", or "don't overthink" into an agent body.

## 3. Size Benchmarks

| Category                         | Lines   | Words     |
| -------------------------------- | ------- | --------- |
| Small                            | 100-150 | <800     |
| Medium                           | 150-300 | 800-1,500 |
| Large (review for padding)       | 300+    | 2,000+    |

**Size is a signal, not a target.** A long agent is worth reviewing, but cut a line only because it fails the test in `anthropic-best-practices.md` Section 1 (the model already knows it, it duplicates inherited context from CLAUDE.md/rules, or it is a verbose example), never to hit a line count. Agents are single `.md` files; do not extract content to separate files.

## 4. Output Format Patterns

All agents use structured output templates. Common structure:

1. **Verdict header** — `## VERDICT: SUCCESS/ROLLBACK/BLOCKED/SAFE/RISKY`
2. **Evidence sections** — Tables or lists with specific findings
3. **Reasoning** — Why this verdict was reached
4. **Actionable next steps** — Exact commands or file changes needed

Agents feeding orchestrators use rigid parseable formats. Standalone agents use human-readable reports.

## 5. Handoff Patterns

| Pattern                     | Description                                                          |
| --------------------------- | -------------------------------------------------------------------- |
| GitHub issue comment        | Post results as GitHub issue comment                                 |
| Structured return to caller | Return verdict + evidence for calling skill to parse                 |
| Terminal states             | Named end states (SUCCESS/ROLLBACK/PARTIAL) with different templates |
| Fix-and-retry loop          | Return BLOCKED with exact fixes; caller applies and re-invokes       |

Agents never chain directly to each other. Results flow through skills or the main conversation.

## 6. Description Field Patterns

**Structure:** All well-formed descriptions follow this pattern:

1. Brief capability statement (1 sentence)
2. Triggering conditions ("When to use"), as categories of intent
3. Anti-conditions ("When NOT to use"), naming the alternative

**Template:**

```text
<Brief capability statement — what the agent does, one sentence.>

**When to use:**
- <Category of request or event that should trigger this agent>
- <Category 2>

**When NOT to use:**
- <Anti-condition> (use <alternative> instead)
- <Anti-condition 2>
```

**Anti-patterns:** Flat prose with no when/not-to sections, which hides the agent's boundaries from the parent. Sample user/assistant dialogue, which is loaded into every parent request and anchors routing to the phrasings it shows.
