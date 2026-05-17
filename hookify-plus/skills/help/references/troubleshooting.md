# Troubleshooting

## Hook Not Triggering

- Confirm the rule file is in the `.claude/hookify-plus/` directory.
- Verify `enabled: true` in frontmatter.
- Confirm the pattern is valid regex.
- Test the pattern: `python3 -c "import re; print(re.search(r'your_pattern', 'test_text'))"`.
- Rules take effect immediately - no restart needed.

## Import Errors

- Check Python 3 is available: `python3 --version`.
- Verify the hookify plugin is installed correctly.

## Pattern Not Matching

- Test regex separately outside hookify.
- Check for escaping issues (use unquoted patterns in YAML).
- Try a simpler pattern first, then refine.
- Confirm the `event` field matches the operation type (bash, file, stop, prompt).

## Rule File Not Detected

- Ensure the file is in `.claude/hookify-plus/` and ends with `.md`.
- Verify the file has valid YAML frontmatter between `---` delimiters.
- Check for YAML syntax errors (missing colons, bad indentation).

## Multiple Rules Conflicting

- List all active rules with `/hookify:list`.
- Disable conflicting rules by setting `enabled: false`.
- More specific patterns take precedence - narrow overly broad patterns.
