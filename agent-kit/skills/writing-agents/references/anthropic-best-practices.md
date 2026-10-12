# Anthropic Best Practices for Agent Authoring

Reference material from official Anthropic documentation. Each principle includes actionable guidance and source URL.

## Contents

01. [Token Efficiency](#1-token-efficiency)
02. [Right Altitude](#2-right-altitude)
03. [Emphasis Calibration](#3-emphasis-calibration)
04. [Scope Creep](#4-scope-creep)
05. [Autonomy and Safety](#5-autonomy-and-safety)
06. [Parallel Execution](#6-parallel-execution)
07. [Progressive Disclosure](#7-progressive-disclosure)
08. [Subagent Design](#8-subagent-design)
09. [Tool Scoping](#9-tool-scoping)
10. [Feedback Loops](#10-feedback-loops)
11. [Stop on Error](#11-stop-on-error)
12. [Don't Over-Explain](#12-dont-over-explain)
13. [Don't Duplicate Inherited Context](#13-dont-duplicate-inherited-context)

______________________________________________________________________

## 1. Token Efficiency

Context is finite. Every token competes with conversation history, other skills, and the actual request. "Context rot" degrades recall as token count grows — this is a performance gradient, not a cliff. Challenge each line with one question: could the model already know this? Cut restatements of default behavior and workarounds for failures the current model doesn't have. Minimal is not short: environment facts, the reasons behind rules, the quality bar, and non-obvious commands are what only the author knows, and an agent missing them falls back on generic defaults.

Source: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents

## 2. Right Altitude

Match specificity to task fragility. High freedom (text guidance) for judgment calls where multiple approaches are valid. Low freedom (exact commands) for fragile, error-prone operations. Think: narrow bridge with cliffs = exact commands; open field = general direction.

Source: https://platform.claude.com/docs/en/docs/agents-and-tools/agent-skills/best-practices

## 3. Emphasis Calibration

Current Claude models follow system prompts closely; emphasis written to fix undertriggering causes overtriggering. Replace "CRITICAL: You MUST use this tool when..." with "Use this tool when...". For safety gates, make the stop unconditional and give the reason; the reason and a named end state hold the gate, not capitals or bold.

Source: https://platform.claude.com/docs/en/docs/build-with-claude/prompt-engineering/claude-4-best-practices

## 4. Scope Creep

If testing shows an agent creating extra files, abstractions, or unrequested flexibility, add a targeted line: "Only make changes that are directly requested." Add it when observed, not by default.

Source: https://platform.claude.com/docs/en/docs/build-with-claude/prompt-engineering/claude-4-best-practices

## 5. Autonomy and Safety

Without guidance, an agent may take actions that are hard to reverse — deleting files, force-pushing, posting to external services. Agents performing destructive or externally-visible operations should include confirmation gates. Add explicit guidance on which actions require user confirmation vs. which can proceed autonomously.

Source: https://platform.claude.com/docs/en/docs/build-with-claude/prompt-engineering/claude-4-best-practices

## 6. Parallel Execution

State which checks are independent and which depend on earlier results, so independent ones run in parallel. Example: "These checks can run in parallel: [list]. Run these after the above pass: [list]."

Source: https://platform.claude.com/docs/en/docs/build-with-claude/prompt-engineering/claude-4-best-practices

## 7. Progressive Disclosure

Claude Code loads every agent's `description` into each parent request and loads the body only when the agent runs. Keep routing text in the description and everything else in the body. Agents are single files; when an agent needs depth that already lives in the repo (a component README, a runbook), point it at that file instead of copying the content in.

Source: https://code.claude.com/docs/en/sub-agents

## 8. Subagent Design

One clear goal, input, output, and handoff rule per agent. Well-scoped tools make it easier for Claude to decide next steps. Minimize tool set overlap. If an agent spawns subagents where a direct lookup would do, say when not to.

Sources: https://claude.com/blog/building-agents-with-the-claude-agent-sdk, https://platform.claude.com/docs/en/docs/build-with-claude/prompt-engineering/claude-4-best-practices

## 9. Tool Scoping

Least privilege. Restrict to essential tools. Read-only agents should not have Write/Edit. Operational agents need Bash. Analysis agents need Read, plus Bash for search: this harness has no Grep or Glob tool, so list only tools that exist here. Tools are prominent in Claude's context window, making them the primary actions Claude considers — be conscious about which tools you expose.

Source: https://claude.com/blog/building-agents-with-the-claude-agent-sdk

## 10. Feedback Loops

Run validator -> fix errors -> repeat. This pattern greatly improves output quality. Structure output for the calling agent to parse and act on. Provide exact fixes (file paths, line numbers, corrected code), not vague guidance. Three approaches: rules-based feedback, visual verification, LLM-as-judge.

Sources: https://claude.com/blog/building-agents-with-the-claude-agent-sdk, https://platform.claude.com/docs/en/docs/agents-and-tools/agent-skills/best-practices

## 11. Stop on Error

For sequential multi-step workflows, add explicit termination conditions at each step. If an intermediate step fails, halt execution and report — do not continue to subsequent steps. Example patterns: "Do not proceed if linting fails", "If defrag fails on any node, stop and report." This prevents cascading failures where a broken intermediate state causes worse damage in later steps.

Source: Observed pattern in multi-step agent workflows

## 12. Don't Over-Explain

The models agents run on (`opus`, `sonnet`) already know Kubernetes, YAML, Git, common tools, and standard libraries. Remove explanations of concepts the model understands. Focus on project-specific context it can't infer. Only add context Claude doesn't already have. Challenge each piece: "Can I assume Claude knows this?"

Source: https://platform.claude.com/docs/en/docs/agents-and-tools/agent-skills/best-practices

## 13. Don't Duplicate Inherited Context

Agents inherit CLAUDE.md and project rules automatically. Don't repeat secret handling rules, git conventions, or workflow constraints already in rules files. Reference them if needed ("follow inherited rules for X"), don't copy them.

Source: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
