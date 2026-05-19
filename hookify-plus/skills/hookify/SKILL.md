---
name: hookify
description: This skill should be used when the user asks to "create a hookify rule", "hookify this behavior", "prevent this from happening again", "analyze conversation for unwanted behaviors", or invokes /hookify with or without arguments.
---

# Hookify — Create Hooks from Unwanted Behaviors

**FIRST:** Load the `hookify-plus:writing-rules` skill using the Skill tool to understand rule file format and syntax.

Create hook rules to prevent problematic behaviors by analyzing the conversation or acting on explicit user instructions.

## Step 1: Gather Behavior Information

**If `$ARGUMENTS` is provided:**

- Parse the user's specific instructions from `$ARGUMENTS`.
- Also scan recent conversation (last 10-15 user messages) for additional context and examples of the behavior occurring.

**If `$ARGUMENTS` is empty:**

- Launch the conversation-analyzer agent via the Task tool to find problematic behaviors.
- The agent scans user messages for frustration signals, corrections, repeated issues, and explicit avoidance requests.

**Conversation-analyzer agent prompt:**

```
{
  "subagent_type": "general-purpose",
  "description": "Analyze conversation for unwanted behaviors",
  "prompt": "You are analyzing a Claude Code conversation to find behaviors the user wants to prevent.

Read user messages in the current conversation and identify:
1. Explicit requests to avoid something (\"don't do X\", \"stop doing Y\")
2. Corrections or reversions (user fixing Claude's actions)
3. Frustrated reactions (\"why did you do X?\", \"I didn't ask for that\")
4. Repeated issues (same problem multiple times)

For each issue found, extract:
- What tool was used (Bash, Edit, Write, etc.)
- Specific pattern or command
- Why it was problematic
- User's stated reason

Return findings as a structured list with:
- category: Type of issue
- tool: Which tool was involved
- pattern: Regex or literal pattern to match
- context: What happened
- severity: high/medium/low

Focus on the most recent issues (last 20-30 messages). Don't go back further unless explicitly asked."
}
```

## Step 2: Present Findings to the User

After gathering behaviors (from arguments or the agent), present findings using AskUserQuestion.

**Question 1 — Which behaviors to hookify:**

- Header: "Create Rules"
- multiSelect: true
- Options: List each detected behavior (max 4)
  - Label: Short description (e.g., "Block rm -rf")
  - Description: Why it is problematic

**Question 2 — Action for each selected behavior:**

- "Should this block the operation or just warn?"
- Options:
  - "Just warn" (action: warn — shows message but allows)
  - "Block operation" (action: block — prevents execution)

**Question 3 — Pattern refinement:**

- "What patterns should trigger this rule?"
- Show detected patterns and allow the user to refine or add more.

## Step 3: Generate Rule Files

For each confirmed behavior, create a `.claude/hookify-plus/{rule-name}.md` file.

**Rule naming convention:**

- Use kebab-case.
- Be descriptive: `block-dangerous-rm`, `warn-console-log`, `require-tests-before-stop`.
- Start with an action verb: block, warn, prevent, require.

**Basic rule format:**

```markdown
---
name: {rule-name}
enabled: true
event: {bash|file|stop|prompt|all}
pattern: {regex pattern}
action: {warn|block}
---

{Message to show Claude when rule triggers}
```

**Advanced format (multiple conditions):**

```markdown
---
name: {rule-name}
enabled: true
event: file
conditions:
  - field: file_path
    operator: regex_match
    pattern: \.env$
  - field: new_text
    operator: contains
    pattern: API_KEY
---

{Warning message}
```

## Step 4: Create Files and Confirm

**IMPORTANT:** Rule files must be created in the current working directory's `.claude/hookify-plus/` folder, NOT the plugin directory.

1. Check if `.claude/hookify-plus/` directory exists in the current working directory.

   - If not, create it: `mkdir -p .claude/hookify-plus`

2. Use the Write tool to create each `.claude/hookify-plus/{name}.md` file.

   - Use the project's `.claude/hookify-plus/` path, not the plugin's.

3. Show the user what was created:

   ```
   Created 3 hookify rules:
   - .claude/hookify-plus/dangerous-rm.md
   - .claude/hookify-plus/console-log.md
   - .claude/hookify-plus/sensitive-files.md

   These rules will trigger on:
   - dangerous-rm: Bash commands matching "rm -rf"
   - console-log: Edits adding console.log statements
   - sensitive-files: Edits to .env or credentials files
   ```

4. Verify files were created in the correct location by listing them.

5. Inform the user: **"Rules are active immediately — no restart needed!"**

   The hookify hooks are already loaded and read new rules on the next tool use.

## Additional Resources

- `references/event-types.md` — Detailed event type guide with examples and field reference for each event
- `references/pattern-tips.md` — Regex basics, common patterns by category, testing tips, and pitfalls
- `references/troubleshooting.md` — Debugging rule creation failures, non-triggering rules, and example end-to-end workflow
